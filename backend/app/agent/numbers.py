import re
from dataclasses import dataclass

from app.agent.finance import Computation
from app.agent.state import Block, BulletList, Fact, Paragraph

# Nombres écrits à la française : séparateurs de milliers en espace fine
# insécable, insécable ou ordinaire, virgule décimale.
_SEPARATORS = "   "
_NUMBER = re.compile(rf"\d[\d{_SEPARATORS}]*(?:,\d+)?")

# En deçà de ce seuil, un entier est presque toujours structurel : « année 1 »,
# « trois axes », « douze mois ». Les vérifier produirait un bruit qui
# masquerait les vrais chiffres inventés. La tolérance a un coût — un budget de
# 5 € passerait — et il est accepté.
_STRUCTURAL_MAX = 12

# Marge relative accordée à l'arrondi quand le texte est moins précis que la
# source. « environ 184 600 € » doit passer pour 184 615,38.
_CONTEXT_CHARS = 40


@dataclass(frozen=True)
class Written:
    """Un nombre tel qu'il apparaît dans le brouillon."""

    written: str
    value: float
    context: str


def _to_float(written: str) -> float | None:
    cleaned = written
    for separator in _SEPARATORS:
        cleaned = cleaned.replace(separator, "")
    try:
        return float(cleaned.replace(",", "."))
    except ValueError:
        return None


def _texts(blocks: list[Block]) -> list[str]:
    """Paragraphes et listes seulement.

    Les tableaux viennent tels quels de `Computation.rows` : leurs nombres
    sont traçables par construction, et les réexaminer ferait échouer des
    chiffres parfaitement sourcés sur des questions de mise en forme. Les
    marqueurs à compléter ne portent rien à vérifier.
    """
    textes: list[str] = []
    for block in blocks:
        if isinstance(block, Paragraph):
            textes.append(block.text)
        elif isinstance(block, BulletList):
            textes.extend(block.items)
    return textes


def extract_numbers(blocks: list[Block]) -> list[Written]:
    found: list[Written] = []
    for text in _texts(blocks):
        for match in _NUMBER.finditer(text):
            raw = match.group().strip(_SEPARATORS)
            valeur = _to_float(raw)
            if valeur is None:
                continue
            begin = max(0, match.start() - _CONTEXT_CHARS)
            found.append(Written(written=raw, value=valeur,
                                   context=text[begin:match.end() + _CONTEXT_CHARS]))
    return found


def _decimals(written: str) -> int:
    _, _, fraction = written.partition(",")
    return len(fraction)


def _matches(candidate: Written, known: float) -> bool:
    """Compare à la précision de ce qui est écrit, pas à celle de la source.

    Le modèle arrondit, et c'est souhaitable : « environ 184 600 € » se lit
    mieux que la valeur exacte. On arrondit donc la valeur connue au même
    nombre de chiffres significatifs que le texte en a retenu, puis on
    compare. Un taux stocké en fraction — 0,65 — se retrouve aussi écrit en
    pourcentage, d'où le second essai.
    """
    for reference in (known, known * 100):
        if reference == 0:
            if candidate.value == 0:
                return True
            continue
        decimals = _decimals(candidate.written)
        # Nombre de chiffres significatifs conservés par le texte.
        magnitude = len(str(int(abs(reference)))) if abs(reference) >= 1 else 1
        for kept in range(1, magnitude + 1):
            factor = 10 ** (magnitude - kept)
            if round(reference / factor) * factor == round(candidate.value / factor) * factor:
                return True
        if round(reference, decimals) == round(candidate.value, decimals):
            return True
    return False


def orphan_numbers(
    blocks: list[Block],
    facts: dict[str, Fact],
    computations: list[Computation],
) -> list[Written]:
    """Les nombres du brouillon qui ne viennent ni d'un fait ni d'un calcul.

    Aucun appel à un modèle. C'est ce nœud qui rend tenable le choix de ne pas
    utiliser la recherche web : un chiffre inventé est attrapé par une
    expression régulière, pas par un jugement.
    """
    known_numbers: list[float] = [
        float(fact.value)
        for fact in facts.values()
        if isinstance(fact.value, (int, float)) and not isinstance(fact.value, bool)
    ]
    for computation in computations:
        known_numbers.extend(computation.numbers)

    orphans: list[Written] = []
    for candidate in extract_numbers(blocks):
        if candidate.value == int(candidate.value) and abs(candidate.value) <= _STRUCTURAL_MAX:
            continue
        if any(_matches(candidate, known) for known in known_numbers):
            continue
        orphans.append(candidate)
    return orphans
