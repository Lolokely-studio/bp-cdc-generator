"""Ce qui relie les faits d'un projet aux hypothèses des calculs.

Une couche à part, et non quelques lignes dans le nœud `compute`, parce que
ce sont des règles de métier : les charges fixes annuelles se composent, le
taux de marge se déduit, un délai de paiement en jours devient un besoin en
fonds de roulement. Chacune mérite d'être lue, discutée et testée pour
elle-même.

Chaque constructeur rend `None` quand un fait lui manque. Le calcul est alors
sauté, son tableau n'existe pas, et le texte porte une donnée à compléter —
jamais une valeur par défaut, qui serait un chiffre inventé de plus.
"""

from collections.abc import Callable

from pydantic import BaseModel

from app.agent import finance
from app.agent.facts import Fact

# Un an de charges mensuelles, douze mois de trésorerie, trois ans d'amortissement.
_MONTHS = 12
_DEPRECIATION_YEARS = 3
_DAYS_PER_MONTH = 30


def _value(facts: dict[str, Fact], fact_id: str) -> float | None:
    """La valeur numérique d'un fait, ou `None` s'il manque ou s'il est
    inconnu. « Je ne sais pas » se comporte ici comme une absence : on ne
    calcule pas dessus, on le déclare en hypothèse dans le texte."""
    fact = facts.get(fact_id)
    if fact is None or fact.value is None:
        return None
    if isinstance(fact.value, bool) or not isinstance(fact.value, (int, float)):
        return None
    return float(fact.value)


def _rate(facts: dict[str, Fact], fact_id: str) -> float | None:
    """Un taux, ramené à une fraction.

    La convention est qu'un fait de type `pourcentage` porte une fraction —
    0,35 pour trente-cinq pour cent. Mais un utilisateur tape « 35 », et le
    refuser serait pédant. Au-dessus de 1, on divise. La valeur 1 exactement
    reste ambiguë et se lit en fraction, donc cent pour cent : le cas est rare
    et vaut mieux qu'une devinette.
    """
    value = _value(facts, fact_id)
    if value is None:
        return None
    return value / 100 if value > 1 else value


def _annual_revenue(facts: dict[str, Fact]) -> float | None:
    price = _value(facts, "prix_moyen_unite")
    volume = _value(facts, "volume_ventes_an1")
    if price is None or volume is None:
        return None
    return price * volume


def _annual_fixed_costs(facts: dict[str, Fact]) -> float | None:
    """Les charges fixes de l'année. Le catalogue les demande en deux morceaux
    — un montant mensuel et une masse salariale annuelle — parce que c'est
    ainsi qu'un porteur de projet les connaît."""
    monthly = _value(facts, "charges_fixes_mensuelles")
    payroll = _value(facts, "masse_salariale_an1")
    if monthly is None or payroll is None:
        return None
    return monthly * _MONTHS + payroll


def _gross_margin_rate(facts: dict[str, Fact]) -> float | None:
    price = _value(facts, "prix_moyen_unite")
    variable = _value(facts, "cout_variable_unitaire")
    if price is None or variable is None or price <= 0:
        return None
    return (price - variable) / price


def _investments(facts: dict[str, Fact]) -> float | None:
    initial = _value(facts, "investissements_initiaux")
    development = _value(facts, "budget_developpement")
    if initial is None and development is None:
        return None
    return (initial or 0.0) + (development or 0.0)


def _working_capital(facts: dict[str, Fact]) -> float | None:
    """Le besoin en fonds de roulement, approché par le délai de paiement.

    Le catalogue ne le demande pas — il demande un délai client en jours, ce
    qu'un porteur de projet sait dire. Le chiffre d'affaires immobilisé
    pendant ce délai en est une approximation honnête, et le texte de la
    section la déclare comme telle."""
    revenue = _annual_revenue(facts)
    delay_days = _value(facts, "delai_paiement_clients")
    if revenue is None or delay_days is None:
        return None
    return revenue * (delay_days / _DAYS_PER_MONTH) / _MONTHS


def _market(facts: dict[str, Fact]) -> BaseModel | None:
    tam = _value(facts, "taille_marche_tam")
    sam = _value(facts, "taille_marche_sam")
    som = _value(facts, "taille_marche_som")
    if None in (tam, sam, som):
        return None
    return finance.MarketAssumptions(
        total_market=tam, reachable_market=sam, capturable_market=som
    )


def _unit(facts: dict[str, Fact]) -> BaseModel | None:
    price = _value(facts, "prix_moyen_unite")
    variable = _value(facts, "cout_variable_unitaire")
    if price is None or variable is None:
        return None
    return finance.UnitAssumptions(unit_price=price, variable_cost_per_unit=variable)


def _investment_table(facts: dict[str, Fact]) -> BaseModel | None:
    lines = []
    for fact_id, label in (
        ("investissements_initiaux", "Investissements initiaux"),
        ("budget_developpement", "Développement"),
    ):
        amount = _value(facts, fact_id)
        if amount:
            lines.append(finance.InvestmentLine(
                label=label, amount=amount, duration_years=_DEPRECIATION_YEARS
            ))
    return finance.InvestmentAssumptions(lines=lines) if lines else None


def _income(facts: dict[str, Fact]) -> BaseModel | None:
    revenue = _annual_revenue(facts)
    growth = _rate(facts, "hypothese_croissance")
    margin = _gross_margin_rate(facts)
    fixed = _annual_fixed_costs(facts)
    investments = _investments(facts)
    if None in (revenue, growth, margin, fixed) or investments is None:
        return None
    return finance.IncomeAssumptions(
        first_year_revenue=revenue,
        annual_growth=growth,
        gross_margin_rate=margin,
        fixed_costs=fixed,
        depreciation=investments / _DEPRECIATION_YEARS,
    )


def _cash(facts: dict[str, Fact]) -> BaseModel | None:
    revenue = _annual_revenue(facts)
    monthly = _value(facts, "charges_fixes_mensuelles")
    payroll = _value(facts, "masse_salariale_an1")
    opening = _value(facts, "tresorerie_securite")
    if None in (revenue, monthly, payroll, opening):
        return None
    return finance.CashAssumptions(
        opening_cash=opening,
        monthly_inflow=revenue / _MONTHS,
        monthly_outflow=monthly + payroll / _MONTHS,
    )


def _break_even(facts: dict[str, Fact]) -> BaseModel | None:
    fixed = _annual_fixed_costs(facts)
    margin = _gross_margin_rate(facts)
    revenue = _annual_revenue(facts)
    if fixed is None or margin is None:
        return None
    return finance.BreakEvenAssumptions(
        fixed_costs=fixed, gross_margin_rate=margin, annual_revenue=revenue
    )


def _funding(facts: dict[str, Fact]) -> BaseModel | None:
    investments = _investments(facts)
    working_capital = _working_capital(facts)
    opening = _value(facts, "tresorerie_securite")
    equity = _value(facts, "apport_fondateurs")
    loan = _value(facts, "emprunt_montant")
    grants = _value(facts, "aides_subventions")
    if investments is None or opening is None or equity is None:
        return None
    return finance.FundingAssumptions(
        investments=investments,
        working_capital=working_capital or 0.0,
        opening_cash=opening,
        equity=equity,
        loan=loan or 0.0,
        grants=grants or 0.0,
    )


def _loan(facts: dict[str, Fact]) -> BaseModel | None:
    principal = _value(facts, "emprunt_montant")
    rate = _rate(facts, "taux_interet_emprunt")
    months = _value(facts, "emprunt_duree")
    if not principal or rate is None or not months:
        return None
    # Le catalogue demande la durée en mois ; l'échéancier raisonne en années.
    return finance.LoanAssumptions(
        principal=principal, annual_rate=rate, years=max(1, round(months / _MONTHS))
    )


BUILDERS: dict[str, Callable[[dict[str, Fact]], BaseModel | None]] = {
    "tam_sam_som": _market,
    "marge_unitaire": _unit,
    "tableau_investissements": _investment_table,
    "compte_resultat_3ans": _income,
    "plan_tresorerie_12mois": _cash,
    "seuil_rentabilite": _break_even,
    "point_mort": _break_even,
    "plan_financement_initial": _funding,
    "plan_financement_3ans": _funding,
    "annuites_credit": _loan,
}


def build_assumptions(name: str, facts: dict[str, Fact]) -> BaseModel | None:
    """Les hypothèses d'un calcul, ou `None` si les faits ne suffisent pas."""
    if name not in BUILDERS:
        raise KeyError(f"calcul sans constructeur d'hypothèses : {name}")
    return BUILDERS[name](facts)
