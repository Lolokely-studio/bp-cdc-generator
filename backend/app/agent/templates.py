from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from app.agent.state import SectionRef

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


class SectionTemplate(BaseModel):
    """Une section d'un document, telle que le YAML la déclare.

    Les noms de champs restent ceux du fichier : ce sont des valeurs de
    contrat que trente entrées écrites à la main utilisent déjà, et les
    traduire ici obligerait à traduire dans les deux sens à chaque lecture.
    """

    id: str
    titre: str
    ordre: int
    ordre_lecture: int
    profils: list[str]
    validation: Literal["toujours", "si_note_basse"]
    objectif: str
    depend_de: list[str] = Field(default_factory=list)
    longueur_cible: str
    faits_requis: list[str] = Field(default_factory=list)
    faits_utiles: list[str] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    # Outils déterministes appelés avant la rédaction (§ en-tête de bp.yaml).
    # Absent du cahier des charges, d'où la valeur par défaut vide plutôt
    # qu'un champ requis.
    calculs: list[str] = Field(default_factory=list)
    consignes: str
    grille: list[str] = Field(default_factory=list)


class FactDefinition(BaseModel):
    """Un fait du catalogue.

    `utilise_par` est DÉRIVÉ : l'inverse exact de ce que les sections
    déclarent. Il est chargé tel qu'il est écrit, puis comparé au dérivé par
    un test. On ne le recalcule pas en silence : une divergence est une
    information sur un fichier qui a bougé, pas un détail à rattraper.

    `pivot` est présent dans le catalogue mais décrit nulle part — ni en
    en-tête du fichier, ni dans l'analyse, ni dans la spec. Il est porté pour
    ne pas être perdu ; aucun comportement ne s'y adosse.
    """

    id: str
    libelle: str
    type: str
    unite: str | None = None
    options: list[str] = Field(default_factory=list)
    question: str
    exemple: Any | None = None
    deductible: bool = False
    pivot: bool = False
    utilise_par: list[str] = Field(default_factory=list)


class DocumentTemplate(BaseModel):
    version: str | float
    statut: str
    seuil_relecture: int
    document: Literal["cdc", "bp"]
    profils_disponibles: dict[str, str]
    sections: list[SectionTemplate]


class Catalogue(BaseModel):
    cdc: DocumentTemplate
    bp: DocumentTemplate
    facts: dict[str, FactDefinition]

    @property
    def review_threshold(self) -> int:
        """Les deux documents portent le même seuil ; le lire une seule fois
        évite de choisir lequel fait foi le jour où ils divergeraient."""
        if self.cdc.seuil_relecture != self.bp.seuil_relecture:
            raise ValueError(
                "Les deux templates déclarent des seuils de relecture différents : "
                f"cdc={self.cdc.seuil_relecture}, bp={self.bp.seuil_relecture}"
            )
        return self.cdc.seuil_relecture

    def _document(self, document: str) -> DocumentTemplate:
        """Refuse un document inconnu plutôt que de rendre le business plan par
        défaut : l'annotation `Literal` ne contraint rien à l'exécution, et
        rendre silencieusement le mauvais document produirait un plan complet
        et faux."""
        if document == "cdc":
            return self.cdc
        if document == "bp":
            return self.bp
        raise KeyError(f"document inconnu : {document}")

    def section(self, qualified_id: str) -> SectionTemplate:
        """`qualified_id` est de la forme `bp.compte_resultat`. Les
        identifiants de section ne sont uniques que dans leur document."""
        document, _, section_id = qualified_id.partition(".")
        for section in self._document(document).sections:
            if section.id == section_id:
                return section
        raise KeyError(f"section inconnue : {qualified_id}")

    def fact(self, fact_id: str) -> FactDefinition:
        return self.facts[fact_id]

    def derived_utilise_par(self) -> dict[str, set[str]]:
        """L'inverse exact de ce que les sections déclarent, requis et utiles
        confondus. C'est la valeur de référence contre laquelle le champ écrit
        dans le catalogue est vérifié."""
        # Amorcé sur TOUS les faits, et non seulement sur ceux qu'une section
        # cite. Un fait catalogué que personne n'utilise encore a un
        # `utilise_par` vide : sans cette amorce, le dérivé n'aurait pas la clé
        # tandis que l'écrit l'aurait à `set()`, l'égalité de dictionnaires
        # échouerait, et le message d'erreur afficherait une différence vide —
        # un échec indiagnosticable.
        derive: dict[str, set[str]] = defaultdict(set, {f: set() for f in self.facts})
        for document in (self.cdc, self.bp):
            for section in document.sections:
                for fact_id in (*section.faits_requis, *section.faits_utiles):
                    derive[fact_id].add(f"{document.document}.{section.id}")
        return dict(derive)

    def sections_using(self, fact_id: str) -> set[str]:
        return set(self.facts[fact_id].utilise_par)

    def sections_to_reopen(self, fact_ids: set[str]) -> set[str]:
        """Troisième invariant du §4.2 : modifier un fait rouvre les sections
        que `utilise_par` désigne, et elles seules."""
        to_reopen: set[str] = set()
        for fact_id in fact_ids:
            to_reopen |= self.sections_using(fact_id)
        return to_reopen

    def sections_depending_on(self, qualified_id: str) -> set[str]:
        """La section demandée et, transitivement, celles qui en dépendent.

        `depend_de` nomme des sections du MÊME document, sans préfixe : la
        fermeture ne traverse donc jamais la frontière entre le CDC et le
        business plan. C'est voulu — les deux documents se recoupent par les
        faits, pas par les sections, et c'est `sections_to_reopen` qui porte
        ce chemin-là.

        Transitive, parce qu'une dépendance l'est : si C dépend de B et B de
        A, rouvrir A sans rouvrir C laisserait C appuyée sur un B qui va
        changer. La file évite la récursion, qu'un cycle dans les gabarits
        ferait déborder ; `to_reopen` sert aussi de marquage, donc un cycle
        s'arrête de lui-même.
        """
        document, _, section_id = qualified_id.partition(".")
        template = self._document(document)
        if not any(s.id == section_id for s in template.sections):
            raise KeyError(f"section inconnue : {qualified_id}")

        to_reopen = {qualified_id}
        queue = [section_id]
        while queue:
            current = queue.pop()
            for section in template.sections:
                if current in section.depend_de:
                    qualified = f"{document}.{section.id}"
                    if qualified not in to_reopen:
                        to_reopen.add(qualified)
                        queue.append(section.id)
        return to_reopen

    def plan_for(
        self,
        documents: Literal["cdc", "bp", "both"],
        profil_cdc: str | None,
        profil_bp: str | None,
    ) -> list[SectionRef]:
        """Le plan de production d'un projet.

        Suit `ordre` et non `ordre_lecture` : l'un dit dans quel ordre écrire,
        l'autre dans quel ordre lire, et ils diffèrent — la synthèse du
        business plan s'écrit en dernier et se lit en premier. L'export du
        plan 5 se servira de l'autre.

        Le cahier des charges passe entièrement avant le business plan. Les
        dépendances déclarées ne franchissent jamais la frontière entre les
        deux documents, donc rien n'oblige à les entrelacer, et rédiger le
        besoin avant le modèle économique est l'ordre naturel.
        """
        requested = ("cdc", "bp") if documents == "both" else (documents,)
        profiles = {"cdc": profil_cdc, "bp": profil_bp}
        plan: list[SectionRef] = []
        for document in requested:
            profil = profiles[document]
            if profil is None:
                raise ValueError(f"aucun profil choisi pour le document {document}")
            template = self._document(document)
            if profil not in template.profils_disponibles:
                raise ValueError(f"profil inconnu pour {document} : {profil}")
            selected = sorted(
                (s for s in template.sections if profil in s.profils),
                key=lambda s: s.ordre,
            )
            for section in selected:
                plan.append(
                    SectionRef(
                        document=document,
                        section_id=section.id,
                        order=len(plan) + 1,
                    )
                )
        return plan


def _read(name: str) -> dict:
    return yaml.safe_load((_TEMPLATES / name).read_text(encoding="utf-8"))


@lru_cache
def load_catalogue() -> Catalogue:
    """Lecture unique par processus. Les fichiers sont versionnés avec le
    code : ils ne changent pas sous une application qui tourne."""
    facts_raw = _read("catalogue-faits.yaml")["faits"]
    return Catalogue(
        cdc=DocumentTemplate(**_read("cdc.yaml")),
        bp=DocumentTemplate(**_read("bp.yaml")),
        facts={f["id"]: FactDefinition(**f) for f in facts_raw},
    )
