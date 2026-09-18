import pytest

from app.agent.finance import BreakEvenAssumptions, run_computation
from app.agent.numbers import extract_numbers, orphan_numbers
from app.agent.state import BulletList, Fact, Paragraph, Placeholder, Table


def _fact(fact_id, value):
    return Fact(fact_id=fact_id, value=value, source="user")


THRESHOLD = run_computation("seuil_rentabilite", BreakEvenAssumptions(
    fixed_costs=120_000, gross_margin_rate=0.65,
))  # 184 615,38


def test_numbers_are_read_out_of_french_typography():
    blocks = [Paragraph(text="Le seuil s'établit à 184 615,38 € pour 120 000 € de charges.")]
    lus = [n.value for n in extract_numbers(blocks)]
    assert 184_615.38 in lus
    assert 120_000 in lus


def test_thin_and_non_breaking_spaces_are_read_as_thousands():
    blocks = [Paragraph(text="Un marché de 4 500 000 € et un autre de 90 000 €.")]
    assert [n.value for n in extract_numbers(blocks)] == [4_500_000, 90_000]


def test_a_number_backed_by_a_fact_is_not_an_orphan():
    blocks = [Paragraph(text="Le budget de développement est de 60 000 €.")]
    assert orphan_numbers(blocks, {"budget": _fact("budget", 60_000)}, []) == []


def test_a_number_backed_by_a_computation_is_not_an_orphan():
    blocks = [Paragraph(text="Il faut réaliser 184 615,38 € pour couvrir les charges.")]
    assert orphan_numbers(blocks, {}, [THRESHOLD]) == []


def test_a_rounded_computation_output_is_not_an_orphan():
    # Le modèle arrondit, et c'est souhaitable : « environ 184 600 € » se lit
    # mieux. Refuser l'arrondi rendrait la rédaction impossible.
    blocks = [Paragraph(text="Il faut environ 184 600 € de chiffre d'affaires.")]
    assert orphan_numbers(blocks, {}, [THRESHOLD]) == []


def test_a_percentage_matches_a_rate_stored_as_a_fraction():
    blocks = [Paragraph(text="La marge brute atteint 65 %.")]
    assert orphan_numbers(blocks, {"taux": _fact("taux", 0.65)}, []) == []


@pytest.mark.parametrize(("written", "expected"), [
    ("184 615,38", 0.01),
    ("184 600", 100.0),
    ("200 000", 100_000.0),
    ("10 000", 10_000.0),
    ("3 450 000", 10_000.0),
    ("65", 1.0),
])
def test_the_step_a_writing_claims(written, expected):
    """Épingle l'étape elle-même, et pas seulement le verdict final.

    Une première version comptait les zéros de fin sans retirer les
    séparateurs de milliers : « 200 000 » ne rendait que trois zéros au lieu
    de cinq. Les tests de verdict passaient quand même, pour la mauvaise
    raison — l'intervalle échouait là où c'est l'écart relatif qui devait
    trancher. Un test sur la valeur intermédiaire l'aurait vu tout de suite.
    """
    from app.agent.numbers import _written_step

    assert _written_step(written) == expected


@pytest.mark.parametrize(("written", "known"), [
    ("3 450 000", 3_451_234.0),
    ("1 200 000", 1_205_678.0),
    ("200 000", 201_500.0),
])
def test_a_grouped_round_figure_is_a_legitimate_rounding(written, known):
    # L'autre direction : resserrer un vérificateur est le moment exact où on
    # le rend trop strict. Ces trois-là sont des arrondis que n'importe quel
    # rédacteur écrirait, à moins d'un pour cent de la valeur réelle.
    blocks = [Paragraph(text=f"Le marché pèse {written} € selon l'étude citée.")]
    assert orphan_numbers(blocks, {"marche": _fact("marche", known)}, []) == []


def test_a_fact_worth_a_hundredth_of_a_figure_does_not_source_it():
    # La branche pourcentage n'a de sens que pour une fraction. Sans cette
    # borne, un effectif de 65 personnes rendait « 6 500 € » traçable.
    blocks = [Paragraph(text="Un investissement de 6 500 € pour le nouveau site.")]
    orphans = orphan_numbers(blocks, {"effectif": _fact("effectif", 65)}, [])
    assert [o.value for o in orphans] == [6_500]


def test_an_invented_figure_close_to_a_real_one_is_still_an_orphan():
    # Le défaut qu'une première version laissait passer : 62 700 n'est pas un
    # arrondi de 60 000, mais un comparateur qui essayait toutes les précisions
    # l'acceptait dans le godet « 6 × 10⁴ ».
    blocks = [Paragraph(text="Le budget de développement est de 62 700 €.")]
    orphans = orphan_numbers(blocks, {"budget": _fact("budget", 60_000)}, [])
    assert [o.value for o in orphans] == [62_700]


@pytest.mark.parametrize("invented", ["150 000", "200 000", "249 000"])
def test_a_figure_in_the_neighbourhood_of_a_computation_is_not_a_rounding(invented):
    # Les trois que la relecture a exhibés. « 200 000 » est le plus retors :
    # 184 615,38 tombe bien dans l'intervalle que ses cinq zéros désignent,
    # mais 8 % d'écart ne se lit pas comme un arrondi.
    blocks = [Paragraph(text=f"Il faut réaliser {invented} € pour couvrir les charges.")]
    assert orphan_numbers(blocks, {}, [THRESHOLD])


def test_an_invented_number_is_an_orphan():
    # Le cas pour lequel ce nœud existe.
    blocks = [Paragraph(text="Le marché français pèse 2 400 000 000 € selon nos estimations.")]
    orphans = orphan_numbers(blocks, {"budget": _fact("budget", 60_000)}, [THRESHOLD])
    assert [o.value for o in orphans] == [2_400_000_000]


def test_small_integers_are_left_alone():
    # « Année 1 », « trois axes », « douze mois » : structurels, sans fait
    # derrière. La tolérance est assumée : un budget de 5 € passerait.
    blocks = [Paragraph(text="Le plan couvre 3 exercices et 12 mois de trésorerie.")]
    assert orphan_numbers(blocks, {}, []) == []


def test_tables_are_not_examined():
    # Ils viennent tels quels de Computation.rows : traçables par construction.
    blocks = [Table(number=1, title="Seuil", columns=("Poste",), rows=(("999 999 999 €",),))]
    assert orphan_numbers(blocks, {}, []) == []


def test_list_items_are_examined():
    blocks = [BulletList(items=["Un investissement de 777 777 € est prévu."])]
    assert [o.value for o in orphan_numbers(blocks, {}, [])] == [777_777]


def test_placeholders_carry_no_numbers_to_check():
    blocks = [Placeholder(label="Donnée à compléter : chiffre d'affaires 2027")]
    assert orphan_numbers(blocks, {}, []) == []


def test_an_orphan_says_where_it_was_written():
    blocks = [Paragraph(text="Un chiffre de 2 400 000 000 € surgi de nulle part.")]
    orphan = orphan_numbers(blocks, {}, [])[0]
    assert orphan.written == "2 400 000 000"
    assert "surgi de nulle part" in orphan.context
