from app.agent.finance import (
    CashAssumptions,
    IncomeAssumptions,
    cash_plan_12m,
    income_statement_3y,
)
from app.export.charts import charts_for

_PNG = b"\x89PNG\r\n\x1a\n"


def _income():
    return income_statement_3y(IncomeAssumptions(
        first_year_revenue=100_000, gross_margin_rate=0.6, fixed_costs=30_000,
        depreciation=5_000, annual_growth=0.1))


def _cash():
    return cash_plan_12m(CashAssumptions(
        opening_cash=10_000, monthly_inflow=8_000, monthly_outflow=7_000))


def test_the_numbers_layout_the_charts_read_is_the_one_finance_writes():
    """Le contrat de disposition, fixé contre les vraies fonctions. Si
    `finance.py` range autrement ses flottants, c'est ce test qui tombe."""
    income = _income().numbers
    assert income[0] == 100_000            # CA année 1
    assert income[1] == 60_000             # marge brute année 1
    assert income[2] == 25_000             # résultat année 1
    assert round(income[3]) == 110_000     # CA année 2
    cash = _cash().numbers
    assert cash[0] == 11_000               # solde fin du mois 1
    assert cash[11] == 22_000              # solde fin du mois 12


def test_each_known_computation_gives_one_png_chart():
    charts = charts_for({"compte_resultat_3ans": _income(),
                         "plan_tresorerie_12mois": _cash()})
    assert len(charts) == 2
    assert all(c.png.startswith(_PNG) for c in charts)
    assert all(c.title for c in charts)


def test_a_missing_computation_gives_no_chart_and_no_error():
    """Un calcul qui n'a pas tourné (un fait manquant) donne un document
    sans ce graphique, jamais un export en échec."""
    assert charts_for({}) == []
    assert len(charts_for({"compte_resultat_3ans": _income()})) == 1


def test_a_computation_restored_as_a_dict_is_read_too():
    """Relu depuis le point de reprise, un `Computation` peut revenir sous
    forme de dictionnaire selon le sérialiseur. On lit les deux formes."""
    income = _income()
    as_dict = {"name": income.name, "numbers": list(income.numbers)}
    assert len(charts_for({"compte_resultat_3ans": as_dict})) == 1


def test_charts_do_not_depend_on_a_display():
    """Le serveur n'a pas d'écran. Le moteur `Agg` est imposé par le module,
    pas par l'environnement qui l'importe."""
    import matplotlib

    assert matplotlib.get_backend().lower() == "agg"
