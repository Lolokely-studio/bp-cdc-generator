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


# Au-delà de cet écart relatif, un nombre n'est plus l'arrondi d'un autre mais
# un autre nombre. Le garde-fou existe parce que les zéros de fin sont
# ambigus : « 200 000 » peut annoncer une précision à la centaine de mille —
# auquel cas 184 615 tomberait dans son intervalle — ou être exact. On tranche
# en refusant les écarts que personne ne lirait comme un arrondi.
_RELATIVE_TOLERANCE = 0.05


def _written_step(written: str) -> float:
    """L'échelle que l'écriture annonce.

    « 184 615,38 » annonce le centième, « 184 600 » la centaine, « 200 000 »
    la centaine de mille. C'est cette échelle, et non celle de la source, qui
    dit quel écart le texte revendique.
    """
    if "," in written:
        return 10 ** -len(written.split(",", 1)[1])
    digits = written.lstrip("-")
    trailing = len(digits) - len(digits.rstrip("0"))
    return float(10 ** trailing)


def _matches(candidate: Written, known: float) -> bool:
    """Le nombre écrit est-il une lecture arrondie de la valeur connue ?

    Le modèle arrondit, et c'est souhaitable : « environ 184 600 € » se lit
    mieux que la valeur exacte. Deux conditions, et il faut les deux.

    La première : la valeur connue tombe dans l'intervalle que l'écriture
    désigne. « 184 600 » désigne [184 550, 184 650[, où 184 615,38 se trouve.
    « 62 700 » désigne [62 650, 62 750[, où 60 000 ne se trouve pas.

    La seconde : l'écart relatif reste petit. Elle existe pour les zéros de
    fin, qui sur-annoncent la tolérance — sans elle, « 200 000 » vaudrait pour
    n'importe quoi entre 150 000 et 250 000, et le vérificateur laisserait
    passer une bande de ±35 % autour de chaque valeur réelle. C'est le défaut
    qu'une première version de ce plan avait, et qu'une relecture a démontré
    par l'exemple.

    Un taux stocké en fraction — 0,65 — s'écrit aussi en pourcentage, d'où le
    second essai sur `known * 100`.
    """
    step = _written_step(candidate.written)
    for reference in (known, known * 100):
        gap = abs(candidate.value - reference)
        if gap > step / 2:
            continue
        if reference == 0:
            if candidate.value == 0:
                return True
            continue
        if gap / abs(reference) <= _RELATIVE_TOLERANCE:
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
