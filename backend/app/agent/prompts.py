"""Le contrat avec le modèle : prompts assemblés et relecture du texte.

La décision qui porte ce module : le modèle écrit de la prose, pas des blocs.
Une section se diffuse en flux pour que l'utilisateur la voie arriver, mais
son contenu doit finir en blocs typés — jamais du HTML ni du Markdown — parce
que l'export Word part de cette structure. On ne diffuse pas du JSON : un
objet à moitié écrit ne s'affiche pas, et une sortie hors schéma ferait
repartir la section entière. La solution retenue : le modèle écrit un texte
simple, diffusable tel quel, qu'un analyseur déterministe convertit en blocs
à la fin — c'est `parse_written_text` ci-dessous, qui vit dans ce module
avec `WRITING_FORMAT` pour que la consigne et l'analyseur qui la relit
s'accordent au caractère près.
"""

import re

from pydantic import BaseModel, Field

from app.agent.finance import Computation
from app.agent.state import Block, BulletList, Fact, Paragraph, Placeholder, Table
from app.agent.templates import Catalogue, FactDefinition, SectionTemplate, load_catalogue
from app.llm.types import Message

# ---------------------------------------------------------------- schémas

class ExtractedFact(BaseModel):
    fact_id: str
    value: str | float | bool | list[str]
    confidence: float = Field(ge=0, le=1)


class ExtractedFacts(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list)


class ProposedQuestion(BaseModel):
    fact_id: str
    question: str


class ProposedQuestions(BaseModel):
    questions: list[ProposedQuestion] = Field(default_factory=list)


class Critique(BaseModel):
    """`score` est sur dix. Les deux seuils du §4.4 s'y comparent : sous 7 la
    machine réécrit, sous 8 elle réveille l'utilisateur."""

    score: int = Field(ge=0, le=10)
    problems: list[str] = Field(default_factory=list)


class FoundInconsistency(BaseModel):
    kind: str
    description: str
    sections: list[str]
    proposal: str | None = None


class FoundInconsistencies(BaseModel):
    inconsistencies: list[FoundInconsistency] = Field(default_factory=list)


# ------------------------------------------------- le format de rédaction

WRITING_FORMAT = """Format de sortie, à respecter strictement :

- Un paragraphe est un bloc de texte séparé du suivant par une ligne vide.
- Une énumération est une suite de lignes commençant par « - ».
- Une donnée que tu n'as pas s'écrit sur sa propre ligne, seule :
  [Donnée à compléter : ce qui manque]
- Un tableau ne s'écrit pas. Tu places un repère sur sa propre ligne :
  [Tableau: <identifiant>]
  où <identifiant> est celui d'un tableau proposé plus bas. Le tableau sera
  inséré à cet endroit, déjà calculé. Ne recopie jamais ses chiffres dans le
  texte : renvoie-y.

N'écris ni titre de section, ni Markdown, ni HTML, ni numérotation."""

_PLACEHOLDER = re.compile(r"^\[Donnée à compléter\s*:\s*(?P<label>.+?)\]$")
_TABLE = re.compile(r"^\[Tableau\s*:\s*(?P<name>[a-z0-9_]+)\]$")


def parse_written_text(text: str, computations: list[Computation]) -> list[Block]:
    """Convertit la prose diffusée en blocs typés.

    C'est l'autre moitié du contrat décrit par `WRITING_FORMAT`, et c'est
    pourquoi les deux vivent dans le même fichier : séparés, ils
    divergeraient.

    Les tableaux ne sont pas relus mais insérés depuis `computations` : le
    modèle a écrit un repère, pas des chiffres. C'est le corollaire de « le
    modèle ne calcule pas », et la raison pour laquelle le vérificateur de
    chiffres n'examine pas les tableaux.
    """
    by_name = {c.name: c for c in computations}
    blocks: list[Block] = []
    number = 0

    for chunk in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue

        if len(lines) == 1:
            placeholder = _PLACEHOLDER.match(lines[0])
            if placeholder:
                blocks.append(Placeholder(label=placeholder.group("label").strip()))
                continue
            table = _TABLE.match(lines[0])
            if table:
                name = table.group("name")
                if name not in by_name:
                    # Échouer ici fait repartir la section, ce qui est
                    # réparable. Laisser passer produirait un document avec un
                    # trou silencieux à la place d'un tableau.
                    raise ValueError(f"tableau demandé sans calcul correspondant : {name}")
                computation = by_name[name]
                number += 1
                blocks.append(Table(
                    number=number, title=computation.title,
                    columns=list(computation.columns),
                    rows=[list(line) for line in computation.rows],
                ))
                continue

        if all(line.startswith("- ") for line in lines):
            blocks.append(BulletList(items=[line[2:].strip() for line in lines]))
            continue

        blocks.append(Paragraph(text=" ".join(lines)))

    return blocks


# ------------------------------------------------------------- les prompts

_SYSTEM = (
    "Tu rédiges des documents professionnels en français pour une agence. "
    "Tu n'inventes aucun chiffre : tout nombre vient d'un fait fourni ou d'un "
    "tableau déjà calculé. Ce que tu ignores s'écrit en donnée à compléter."
)


def _fact_lines(facts: dict[str, Fact], catalogue: Catalogue | None = None) -> str:
    """Un fait par ligne. Une valeur nulle est présentée comme une ignorance
    assumée, pas comme une absence : le texte doit la déclarer en hypothèse
    plutôt que de la contourner.

    Le libellé retombe sur `fact_id` quand le catalogue ne connaît pas ce
    fait — `Catalogue.fact` lèverait sinon une `KeyError` pour un identifiant
    qui n'est pas encore catalogué, ce qui n'est pas une raison de faire
    échouer la construction du prompt."""
    lines = []
    for fact in facts.values():
        definition = catalogue.facts.get(fact.fact_id) if catalogue else None
        libelle = definition.libelle if definition else fact.fact_id
        if fact.value is None:
            lines.append(f"- {libelle} ({fact.fact_id}) : inconnu — à déclarer en hypothèse")
        else:
            lines.append(f"- {libelle} ({fact.fact_id}) : {fact.value}")
    return "\n".join(lines) or "- aucun fait établi pour l'instant"


def writing_prompt(
    section: SectionTemplate,
    facts: dict[str, Fact],
    computations: list[Computation],
    profil: str,
    catalogue: Catalogue | None = None,
) -> list[Message]:
    """Le prompt de rédaction est assemblé, pas écrit.

    `objectif`, `consignes` et `longueur_cible` viennent du template au
    caractère près : ce sont eux le fruit de l'analyse des documents réels, et
    les paraphraser ici ferait diverger deux formulations de la même règle.

    `catalogue` a une valeur par défaut, mais elle n'est pas `None` : sans le
    catalogue, un fait ne peut s'annoncer que par son identifiant, alors que
    la rédaction a besoin du libellé humain. `load_catalogue` est mise en
    cache par le module qui la définit, donc l'appeler ici ne relit pas les
    fichiers YAML à chaque section.
    """
    catalogue = catalogue or load_catalogue()
    markers = "\n".join(f"[Tableau: {c.name}] — {c.title}" for c in computations)
    body = f"""Section à rédiger : {section.titre}
Profil du document : {profil}
Longueur visée : {section.longueur_cible}

Objectif de la section :
{section.objectif.strip()}

Consignes de rédaction :
{section.consignes.strip()}

Faits établis :
{_fact_lines(facts, catalogue)}

Tableaux disponibles, à placer par leur repère :
{markers or "- aucun"}

{WRITING_FORMAT}"""
    return [Message("system", _SYSTEM), Message("user", body)]


def critique_prompt(section: SectionTemplate, blocks: list[Block]) -> list[Message]:
    """La critique est la grille de la section, rien d'autre. Ajouter des
    critères ici les rendrait invisibles à qui relit les templates."""
    criteria = "\n".join(f"- {c}" for c in section.grille)
    text = "\n\n".join(
        b.text if isinstance(b, Paragraph)
        else "\n".join(f"- {i}" for i in b.items) if isinstance(b, BulletList)
        else f"[Donnée à compléter : {b.label}]" if isinstance(b, Placeholder)
        else f"[Tableau {b.number} : {b.title}]"
        for b in blocks
    )
    body = f"""Évalue cette section sur dix, contre la grille ci-dessous, puis
liste les problèmes constatés. Sois exigeant : une note haute doit se mériter.

Grille :
{criteria}

Section :
{text}

Réponds en JSON : {{"score": <0-10>, "problems": ["…"]}}"""
    return [Message("system", _SYSTEM), Message("user", body)]


def questions_prompt(
    section: SectionTemplate, missing: list[str], catalogue: Catalogue
) -> list[Message]:
    """Les formulations par défaut viennent du catalogue ; le modèle les
    adapte au projet plutôt que d'en inventer."""
    lines = []
    for fact_id in missing:
        definition = catalogue.fact(fact_id)
        line = f"- {fact_id} ({definition.libelle}) : « {definition.question} »"
        if definition.options:
            line += f" — choix possibles : {', '.join(definition.options)}"
        if definition.exemple is not None:
            line += f" — exemple : {definition.exemple}"
        lines.append(line)
    body = f"""Reformule ces questions pour ce projet précis, sans en ajouter
ni en retirer. Garde le sens de chaque formulation par défaut.

Section concernée : {section.titre}

{chr(10).join(lines)}

Réponds en JSON : {{"questions": [{{"fact_id": "…", "question": "…"}}]}}"""
    return [Message("system", _SYSTEM), Message("user", body)]


def extraction_prompt(idea: str, definitions: list[FactDefinition]) -> list[Message]:
    """Seuls les faits marqués `deductible` sont proposés. Offrir les autres
    inviterait le modèle à inventer ce qui ne peut qu'être demandé."""
    deducible = [d for d in definitions if d.deductible]
    lines = "\n".join(f"- {d.id} ({d.libelle}, type {d.type})" for d in deducible)
    body = f"""Extrais de cette idée de projet ce que tu peux en déduire avec
certitude, et rien d'autre. N'invente pas : un fait absent de l'idée ne figure
pas dans ta réponse. Donne une confiance entre 0 et 1.

Idée : {idea}

Faits extractibles :
{lines}

Réponds en JSON : {{"facts": [{{"fact_id": "…", "value": …, "confidence": 0.0}}]}}"""
    return [Message("system", _SYSTEM), Message("user", body)]


def coherence_prompt(sections: list[tuple[str, list[Block]]]) -> list[Message]:
    """Le contrôle final, sur la route `grand_contexte` : les deux documents
    entiers dans un seul appel, parce qu'une incohérence se voit entre eux et
    non à l'intérieur de l'un."""
    sections_body = "\n\n".join(
        f"### {identifier}\n" + "\n".join(
            b.text if isinstance(b, Paragraph) else str(b.model_dump()) for b in blocks
        )
        for identifier, blocks in sections
    )
    body = f"""Relis ces documents ensemble et relève les divergences : un
chiffre qui diffère d'une section à l'autre, une promesse sans moyen en face,
une date incompatible. Ne relève rien qui tienne dans une seule section.

{sections_body}

Réponds en JSON : {{"inconsistencies": [{{"kind": "…", "description": "…",
"sections": ["…"], "proposal": "…"}}]}}"""
    return [Message("system", _SYSTEM), Message("user", body)]
