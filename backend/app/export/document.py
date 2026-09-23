import re
from dataclasses import dataclass, field

from app.agent.state import Block, BulletList, Paragraph, Placeholder, Table

# Le titre de chaque document, tel qu'il s'imprime en page de garde.
_DOCUMENT_TITLES = {
    "cdc": "Cahier des charges",
    "bp": "Business plan",
}

# Le même marqueur que `app.agent.prompts._PLACEHOLDER`, mais NON ancré : on
# le cherche au milieu d'une phrase, là où le parseur du plan 3 le laisse
# quand le modèle ne l'isole pas sur sa ligne.
_EMBEDDED_MARKER = re.compile(r"\[Donnée à compléter\s*:\s*(?P<label>[^\]]+?)\s*\]")


def _texts(block) -> list[str]:
    if isinstance(block, Paragraph):
        return [block.text]
    if isinstance(block, BulletList):
        return list(block.items)
    if isinstance(block, Table):
        return [cell for row in block.rows for cell in row]
    return []


@dataclass
class ExportSection:
    title: str
    blocks: list[Block]


@dataclass
class ExportDocument:
    """Ce que les deux rendus, Word et HTML, lisent. Rien d'autre.

    Un document neutre, sans mise en forme : c'est ce qui garantit que le Word
    et le PDF de repli disent la même chose, même quand ils ne se ressemblent
    pas.
    """

    document: str
    title: str
    sections: list[ExportSection] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    draft: bool = False


def assemble(document: str, project_name: str, profil: str,
             rows: list[dict], catalogue) -> ExportDocument:
    """Assemble le document à partir des lignes `sections` d'un projet.

    L'ordre est celui de LECTURE (`ordre_lecture`) : le résumé exécutif est
    rédigé en dernier et se lit en premier. Trier sur l'ordre de rédaction le
    mettrait à la fin du document.

    Une section du plan absente des lignes, ou dont le contenu est vide,
    reste hors du corps et fait du document un brouillon. Une section
    présente et non vide reste dans le corps quel que soit son statut :
    `skipped` (passée sans validation) et `reopened` (à reprendre) désignent
    toutes deux un texte qui EXISTE, pas une section à taire. Seul le statut
    ≠ `done` fait du document un brouillon — c'est le filigrane, jamais une
    omission silencieuse, qui porte la réserve (constat 1 de la revue
    finale : ce code datait du plan 5, avant que `skipped` change de sens).
    """
    if profil is None:
        # Même garde que `Catalogue.plan_for` : sans profil, aucune section ne
        # passe le filtre, et l'on rendrait un document vide, titré et non
        # brouillon, que rien en aval ne saurait distinguer d'un vrai.
        raise ValueError(f"aucun profil choisi pour le document {document}")
    template = catalogue.cdc if document == "cdc" else catalogue.bp
    planned = sorted((s for s in template.sections if profil in s.profils),
                     key=lambda s: s.ordre_lecture)
    by_id = {row["section_id"]: row for row in rows
             if row["document"] == document}

    result = ExportDocument(
        document=document,
        title=f"{_DOCUMENT_TITLES[document]} — {project_name}",
    )
    table_number = 0
    seen_missing: set[str] = set()
    for section in planned:
        row = by_id.get(section.id)
        if row is None or not row["blocks"]:
            result.draft = True
            continue
        if row["statut"] != "done":
            result.draft = True
        blocks: list[Block] = []
        for block in row["blocks"]:
            if isinstance(block, Table):
                # Une copie, jamais l'objet reçu : l'export lit, il n'écrit
                # pas. `number` stocké repart à 1 à chaque section ; on
                # numérote ici dans l'ordre du document.
                table_number += 1
                block = block.model_copy(update={"number": table_number})
            elif isinstance(block, Placeholder) and block.label not in seen_missing:
                seen_missing.add(block.label)
                result.missing.append(block.label)
            for text in _texts(block):
                for match in _EMBEDDED_MARKER.finditer(text):
                    label = match.group("label").strip()
                    if label not in seen_missing:
                        seen_missing.add(label)
                        result.missing.append(label)
            blocks.append(block)
        result.sections.append(ExportSection(title=section.titre, blocks=blocks))
    return result
