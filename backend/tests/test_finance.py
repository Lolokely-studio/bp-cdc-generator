import pytest

from app.agent.finance import (
    COMPUTATIONS,
    BreakEvenAssumptions,
    CashAssumptions,
    FundingAssumptions,
    IncomeAssumptions,
    InvestmentLine,
    InvestmentAssumptions,
    LoanAssumptions,
    MarketAssumptions,
    UnitAssumptions,
    run_computation,
)


def test_every_computation_declared_by_the_templates_exists():
    # Les sept sections du business plan qui déclarent des calculs en nomment
    # dix. Un nom manquant ici ferait échouer une section en cours de run,
    # après vingt minutes de rédaction.
    attendus = {
        "tam_sam_som", "marge_unitaire", "tableau_investissements",
        "compte_resultat_3ans", "plan_tresorerie_12mois", "seuil_rentabilite",
        "point_mort", "plan_financement_initial", "plan_financement_3ans",
        "annuites_credit",
    }
    assert set(COMPUTATIONS) == attendus


def test_market_size_descends_from_total_to_capturable():
    result = run_computation("tam_sam_som", MarketAssumptions(
        total_market=300_000_000, reachable_market=90_000_000, capturable_market=4_500_000,
    ))
    # Les trois montants rendus tels quels, plus les deux parts déduites :
    # 90M / 300M = 30 %, et 4,5M / 90M = 5 %.
    assert result.numbers[:5] == pytest.approx(
        (300_000_000.0, 90_000_000.0, 4_500_000.0, 0.30, 0.05)
    )
    assert len(result.rows) == 3
    assert result.title


def test_an_incoherent_market_descent_is_refused():
    # Un marché atteignable plus grand que le marché total est une saisie
    # fautive. L'écrire dans un document le rendrait risible.
    with pytest.raises(ValueError):
        run_computation("tam_sam_som", MarketAssumptions(
            total_market=1_000, reachable_market=2_000, capturable_market=500,
        ))


def test_unit_margin():
    result = run_computation("marge_unitaire", UnitAssumptions(
        unit_price=49, variable_cost_per_unit=17.15,
    ))
    # `numbers` porte aussi le prix et le coût variable, pour que l'invariant
    # rows/numbers couvre les deux premières lignes du tableau.
    margin, rate = result.numbers[-2:]
    assert margin == pytest.approx(31.85)
    assert rate == pytest.approx(0.65)


def test_investment_table_totals_and_depreciates():
    result = run_computation("tableau_investissements", InvestmentAssumptions(lines=[
        InvestmentLine(label="Développement de la plateforme", amount=60_000, duration_years=3),
        InvestmentLine(label="Matériel", amount=9_000, duration_years=3),
    ]))
    total, depreciation = result.numbers[-2:]
    assert total == pytest.approx(69_000)
    assert depreciation == pytest.approx(23_000)


def test_income_statement_over_three_years():
    result = run_computation("compte_resultat_3ans", IncomeAssumptions(
        first_year_revenue=180_000, annual_growth=0.35, gross_margin_rate=0.65,
        fixed_costs=95_000, depreciation=8_000,
    ))
    # Calculées, pas devinées : 180 000 puis +35 % par an, 65 % de marge,
    # 95 000 de charges fixes et 8 000 de dotations.
    # Les neuf premiers éléments restent les trois exercices ; les charges
    # fixes et les dotations, constantes d'une année à l'autre, sont ajoutées
    # à la suite pour que l'invariant rows/numbers les couvre aussi.
    assert result.numbers[:9] == pytest.approx(
        (180_000, 117_000, 14_000,
         243_000, 157_950, 54_950,
         328_050, 213_232.5, 110_232.5)
    )


def test_cash_plan_covers_twelve_months_and_flags_the_worst():
    result = run_computation("plan_tresorerie_12mois", CashAssumptions(
        opening_cash=30_000, monthly_inflow=15_000, monthly_outflow=18_500,
    ))
    assert len(result.rows) == 12
    # 30 000 puis −3 500 par mois : le solde reste positif jusqu'au huitième
    # mois inclus et passe sous zéro au neuvième. Les douze premiers éléments
    # sont les soldes mensuels ; les encaissements/décaissements mensuels
    # suivent, ajoutés pour l'invariant rows/numbers.
    last_balance = result.numbers[:12][-1]
    assert last_balance == pytest.approx(30_000 - 12 * 3_500)
    assert last_balance < 0


def test_break_even_revenue():
    result = run_computation("seuil_rentabilite", BreakEvenAssumptions(
        fixed_costs=120_000, gross_margin_rate=0.65,
    ))
    assert result.numbers[0] == pytest.approx(184_615.38, abs=0.01)


def test_break_even_point_in_months():
    # Le point mort n'est pas le seuil : c'est le moment de l'année où il est
    # atteint. Ici il tombe au-delà du douzième mois, donc pas dans l'exercice.
    result = run_computation("point_mort", BreakEvenAssumptions(
        fixed_costs=120_000, gross_margin_rate=0.65, annual_revenue=180_000,
    ))
    months = result.numbers[0]
    assert months == pytest.approx(12.31, abs=0.01)
    assert months > 12


def test_break_even_refuses_a_margin_rate_of_zero():
    # Une division par zéro qui rendrait `inf` finirait imprimée dans le
    # document. Elle doit échouer ici, bruyamment.
    with pytest.raises(ValueError):
        run_computation("seuil_rentabilite", BreakEvenAssumptions(
            fixed_costs=120_000, gross_margin_rate=0,
        ))


def test_initial_funding_plan_balances():
    result = run_computation("plan_financement_initial", FundingAssumptions(
        investments=69_000, working_capital=15_000, opening_cash=10_000,
        equity=30_000, loan=60_000, grants=4_000,
    ))
    # Les trois premiers éléments restent besoins/ressources/écart ; le
    # détail des postes suit, ajouté pour l'invariant rows/numbers.
    needs, resources, gap = result.numbers[:3]
    assert needs == pytest.approx(94_000)
    assert resources == pytest.approx(94_000)
    assert gap == pytest.approx(0)


def test_a_funding_plan_that_does_not_balance_says_so():
    result = run_computation("plan_financement_initial", FundingAssumptions(
        investments=69_000, working_capital=15_000, opening_cash=10_000,
        equity=30_000, loan=40_000, grants=0,
    ))
    # L'écart est le troisième élément (besoins, ressources, écart, ...).
    assert result.numbers[2] == pytest.approx(-24_000)


def test_funding_plan_over_three_years():
    result = run_computation("plan_financement_3ans", FundingAssumptions(
        investments=69_000, working_capital=15_000, opening_cash=10_000,
        equity=30_000, loan=60_000, grants=4_000,
        yearly_cash_flow=[14_000, 54_950, 110_232.5],
        yearly_loan_repayment=[9_231.36, 9_600.61, 9_984.63],
    ))
    assert len(result.rows) >= 3


def test_loan_schedule_amortises_to_zero():
    result = run_computation("annuites_credit", LoanAssumptions(
        principal=50_000, annual_rate=0.04, years=5,
    ))
    # Annuité constante : P·i / (1 − (1+i)^−n). Calculée, pas estimée.
    assert result.numbers[0] == pytest.approx(11_231.36, abs=0.01)
    assert len(result.rows) == 5


def test_the_capital_repaid_adds_up_to_the_principal():
    # Non tautologique, contrairement à « le dernier solde vaut zéro » : ce
    # dernier est forcé par le code, celui-ci se déduit des lignes affichées
    # et échouerait si la formule d'annuité était fausse.
    result = run_computation("annuites_credit", LoanAssumptions(
        principal=50_000, annual_rate=0.04, years=5,
    ))
    repaid = sum(_cell_to_float(row[3]) for row in result.rows)
    assert repaid == pytest.approx(50_000, abs=0.05)


def test_a_loan_without_interest_is_a_plain_division():
    result = run_computation("annuites_credit", LoanAssumptions(
        principal=50_000, annual_rate=0, years=5,
    ))
    assert result.numbers[0] == pytest.approx(10_000)


def _cell_to_float(cell: str) -> float | None:
    """Relit un nombre mis en forme à la française. `None` si la cellule n'en
    porte pas — un intitulé, une mention en toutes lettres."""
    import re

    # Ancré en tête : une cellule numérique commence toujours par le chiffre
    # (ou son signe), tandis qu'un intitulé ordinal comme « Année 3 » ou
    # « Mois 7 » porte le chiffre après du texte — il ne doit pas être pris
    # pour une figure financière.
    match = re.match(r"-?\d[\d   ]*(?:,\d+)?", cell)
    if not match:
        return None
    raw = match.group()
    for separator in (" ", " ", " "):
        raw = raw.replace(separator, "")
    return float(raw.replace(",", "."))


@pytest.mark.parametrize("name", sorted(COMPUTATIONS))
def test_every_number_shown_in_a_table_is_also_in_numbers(name):
    """L'invariant qui relie les deux moitiés de `Computation`.

    Le vérificateur de la tâche 4 n'examine pas les tableaux — ils sont
    traçables par construction — mais il examine la prose, et la prose reprend
    les chiffres des tableaux. Un chiffre affiché ici mais absent de `numbers`
    serait signalé comme inventé dès que le modèle l'écrirait dans une phrase.
    Un test générique vaut mieux que dix relectures à la main.
    """
    result = run_computation(name, EXAMPLES[name])
    known = {round(n, 2) for n in result.numbers}
    known |= {round(n * 100, 2) for n in result.numbers}  # un taux s'affiche en pourcentage
    for row in result.rows:
        for cell in row:
            shown = _cell_to_float(cell)
            if shown is None:
                continue
            assert round(shown, 2) in known, (
                f"{name} : {shown} est affiché dans le tableau mais absent de "
                f"`numbers` — le vérificateur le prendra pour un chiffre inventé"
            )


def test_an_unknown_computation_is_refused():
    with pytest.raises(KeyError):
        run_computation("divination", MarketAssumptions(
            total_market=1, reachable_market=1, capturable_market=1,
        ))


@pytest.mark.parametrize("name", sorted(COMPUTATIONS))
def test_every_result_carries_a_title_columns_and_numbers(name):
    # Le tableau part tel quel dans le document et les nombres partent au
    # vérificateur : un calcul qui ne rendrait ni l'un ni l'autre passerait
    # inaperçu jusqu'à l'export.
    result = run_computation(name, EXAMPLES[name])
    assert result.name == name
    assert result.title
    assert result.columns
    assert result.rows
    assert result.numbers


# Un jeu d'hypothèses par calcul, partagé par les deux tests paramétrés.
EXAMPLES = {
        "tam_sam_som": MarketAssumptions(
            total_market=300_000_000, reachable_market=90_000_000, capturable_market=4_500_000),
        "marge_unitaire": UnitAssumptions(unit_price=10, variable_cost_per_unit=4),
        "tableau_investissements": InvestmentAssumptions(
            lines=[InvestmentLine(label="Matériel", amount=1_000, duration_years=2)]),
        "compte_resultat_3ans": IncomeAssumptions(
            first_year_revenue=1_000, annual_growth=0.1, gross_margin_rate=0.5,
            fixed_costs=100, depreciation=50),
        "plan_tresorerie_12mois": CashAssumptions(
            opening_cash=1_000, monthly_inflow=100, monthly_outflow=50),
        "seuil_rentabilite": BreakEvenAssumptions(fixed_costs=100, gross_margin_rate=0.5),
        "point_mort": BreakEvenAssumptions(fixed_costs=100, gross_margin_rate=0.5,
                                           annual_revenue=1_000),
        "plan_financement_initial": FundingAssumptions(
            investments=100, working_capital=10, opening_cash=10,
            equity=60, loan=60, grants=0),
        "plan_financement_3ans": FundingAssumptions(
            investments=100, working_capital=10, opening_cash=10,
            equity=60, loan=60, grants=0,
            yearly_cash_flow=[10, 20, 30], yearly_loan_repayment=[5, 5, 5]),
    "annuites_credit": LoanAssumptions(principal=1_000, annual_rate=0.02, years=2),
}
