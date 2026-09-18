from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field, TypeAdapter

# `Fact` vit dans `facts` avec la règle qui le fusionne, et non ici : un
# `TypedDict` évalue ses annotations à la construction de la classe, donc
# `EsquisseState` a besoin de l'objet `merge_facts` lui-même, pas de son nom.
# Si `Fact` restait ici, `facts` devrait l'importer en retour et le cycle
# serait réel — il l'a été, et c'est ce qui a fait échouer une première
# tentative. Le sens s'y retrouve : `facts` est le domaine du fait, ce qu'il
# est et comment deux faits se combinent.
from app.agent.facts import Fact, merge_facts

# Réexport délibéré : `state` est la surface publique des données de l'agent,
# et tout le reste du paquet y lit `Fact`.
__all__ = [
    "Block", "BulletList", "EsquisseState", "Fact", "Inconsistency",
    "Paragraph", "Placeholder", "SectionRef", "Table",
    "dump_blocks", "parse_blocks",
]


class Paragraph(BaseModel):
    kind: Literal["paragraph"] = "paragraph"
    text: str


class Table(BaseModel):
    """`number` et `title` ne sont pas décoratifs : les templates exigent que
    chaque tableau porte un numéro et un titre, et l'export Word s'en sert
    pour construire la table des tableaux."""

    kind: Literal["table"] = "table"
    number: int
    title: str
    columns: list[str]
    rows: list[list[str]]


class BulletList(BaseModel):
    kind: Literal["list"] = "list"
    items: list[str]


class Placeholder(BaseModel):
    """Un marqueur à compléter, du genre « Donnée à compléter : source ».

    C'est un bloc et non du texte, pour que l'export puisse le mettre en
    évidence et que le comptage des trous d'un document soit une requête, pas
    une expression régulière sur du texte."""

    kind: Literal["placeholder"] = "placeholder"
    label: str


# Union discriminée sur `kind` : un type inventé par le modèle échoue à la
# validation au lieu de se glisser dans la colonne jsonb et de ressortir à
# l'export, où plus rien ne saurait quoi en faire.
Block = Annotated[
    Paragraph | Table | BulletList | Placeholder,
    Field(discriminator="kind"),
]

_blocks = TypeAdapter(list[Block])


def parse_blocks(raw: list[dict]) -> list[Block]:
    """Relit des blocs venus de `sections.contenu` ou d'une réponse du modèle."""
    return _blocks.validate_python(raw)


def dump_blocks(blocks: list[Block]) -> list[dict]:
    """Rend des dictionnaires prêts pour une colonne jsonb. `mode="json"`
    convertit ce que psycopg ne sait pas sérialiser tout seul."""
    return _blocks.dump_python(blocks, mode="json")


class SectionRef(BaseModel):
    """Une entrée du plan : quel document, quelle section, à quel rang."""

    document: Literal["cdc", "bp"]
    section_id: str
    order: int


class Inconsistency(BaseModel):
    """Une divergence relevée par le contrôle de cohérence final.

    `sections` porte des identifiants qualifiés — `bp.compte_resultat` — parce
    qu'une incohérence relie presque toujours les deux documents."""

    kind: str
    description: str
    sections: list[str]
    proposal: str | None = None


class EsquisseState(TypedDict):
    """L'état du graphe.

    Trois clés gardent leur forme de la base — `documents`, `profil_cdc`,
    `profil_bp` — parce qu'elles recopient une colonne de `projects` et qu'un
    renommage ici obligerait à traduire dans les deux sens à chaque projection.
    Le reste est en anglais comme le reste du code.
    """

    project_id: str
    documents: Literal["cdc", "bp", "both"]
    profil_cdc: Literal["consultation", "cadrage"] | None
    profil_bp: Literal["banque", "investisseur"] | None

    idea: str
    # Le seul champ réduit. LangGraph veut la fonction elle-même : un
    # `TypedDict` évalue cette annotation tout de suite, une chaîne ne
    # marcherait pas.
    facts: Annotated[dict[str, Fact], merge_facts]
    plan: list[SectionRef]
    cursor: int

    draft: list[Block] | None
    score: int | None
    problems: list[str]
    revisions: int
    question_rounds: int
    computations: dict[str, Any]
    # Le lot de questions proposé par `formulate_questions`, consommé par
    # `ask_questions` (tâche 7). Une clé à lui seul plutôt qu'une entrée
    # rangée dans `computations` sous un nom réservé : la première mouture
    # faisait cette économie, mais rien ne vidait `computations` entre les
    # sections, et l'entrée aurait survécu dans chaque point de reprise du
    # reste du run — exactement le coût que la ruse voulait éviter. Une clé
    # dédiée à valeur unique, écrasée à chaque tour, ne coûte pas plus cher à
    # sérialiser qu'un `None`, et ne mélange plus un schéma de questions avec
    # les `Computation` financiers.
    pending_questions: Any | None

    inconsistencies: list[Inconsistency]
