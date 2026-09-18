from typing import Any, Literal

from pydantic import BaseModel


class Fact(BaseModel):
    """La plus petite information qu'il faut détenir pour qu'une section
    devienne rédigeable.

    `value` à `None` avec `source="user"` est la façon dont « je ne sais pas »
    se représente : une réponse, pas une absence. Le fait est alors présent
    dans l'état, donc jamais redemandé, et la rédaction le déclare en
    hypothèse. L'absence d'une clé, elle, signifie que la question n'a pas
    encore été posée.

    `source` n'a que deux valeurs. La spec ne fixe que `"user"` ; `"deduced"`
    est choisi ici. Elles sont écrites telles quelles dans `facts.source`.
    """

    fact_id: str
    value: Any | None
    source: Literal["user", "deduced"]
    confidence: float | None = None


def merge_facts(current: dict[str, Fact], incoming: dict[str, Fact]) -> dict[str, Fact]:
    """Fusionne les faits sans qu'une déduction écrase jamais une réponse.

    C'est la seule règle non triviale de l'état, et elle tient en une ligne :
    un fait dont la source est `user` ne cède qu'à un autre fait `user`.

    Ce qu'elle achète : l'extraction peut se tromper sans conséquence. Elle
    tourne sur l'idée saisie, propose des valeurs, et tout ce qu'elle propose
    s'efface devant ce que l'utilisateur a réellement dit — y compris devant
    un « je ne sais pas », qui est un fait `user` à valeur nulle et non une
    absence.

    Les deux dictionnaires sont laissés intacts. LangGraph appelle ce
    réducteur à chaque mise à jour et réutilise les objets qu'il lui passe :
    muter l'entrée corromprait des points de reprise déjà écrits.
    """
    merged = dict(current)
    for fact_id, fact in incoming.items():
        existing = merged.get(fact_id)
        if existing is not None and existing.source == "user" and fact.source != "user":
            continue
        merged[fact_id] = fact
    return merged
