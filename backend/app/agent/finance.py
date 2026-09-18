"""Les dix calculs financiers du business plan.

La décision qui porte ce module : le modèle ne calcule pas. Il structure des
hypothèses — les classes pydantic ci-dessous — et ces fonctions font
l'arithmétique. C'est ce qui rend tenable le choix de ne pas utiliser la
recherche web : un chiffre du document vient d'un fait saisi ou d'ici, jamais
d'une génération. Le vérificateur de la tâche 4 s'appuie sur
`Computation.numbers` pour le prouver section par section.
"""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Computation:
    """Le résultat d'un calcul outillé.

    Deux façons de lire la même chose, parce que deux lecteurs en ont besoin :
    `rows` est mis en forme et part tel quel dans le document — le modèle le
    recopie, il ne le recompose pas —, tandis que `numbers` porte les
    flottants bruts pour le vérificateur de chiffres. Dériver l'un de l'autre
    par expression régulière serait fragile dans les deux sens.
    """

    name: str
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    numbers: tuple[float, ...]


# Espace fine insécable entre les milliers, comme l'usage typographique
# français, et virgule décimale. Le document est en français.
def _money(value: float) -> str:
    return f"{value:,.2f} €".replace(",", " ").replace(".", ",", 1)


def _rate(value: float) -> str:
    return f"{value * 100:.1f} %".replace(".", ",")


class MarketAssumptions(BaseModel):
    total_population: float = Field(gt=0)
    average_annual_spend: float = Field(gt=0)
    reachable_share: float = Field(gt=0, le=1)
    capturable_share: float = Field(gt=0, le=1)


def market_size(a: MarketAssumptions) -> Computation:
    """TAM, SAM, SOM. On descend du marché total au marché réellement visé,
    sans saut de raisonnement : c'est ce que la grille de la section exige."""
    tam = a.total_population * a.average_annual_spend
    sam = tam * a.reachable_share
    som = sam * a.capturable_share
    return Computation(
        name="tam_sam_som",
        title="Taille du marché adressable",
        columns=("Niveau", "Part retenue", "Valeur annuelle"),
        rows=(
            ("Marché total (TAM)", "100 %", _money(tam)),
            ("Marché adressable (SAM)", _rate(a.reachable_share), _money(sam)),
            ("Marché atteignable (SOM)", _rate(a.capturable_share), _money(som)),
        ),
        # La première ligne affiche « 100 % » en toutes lettres : ce n'est
        # une hypothèse nulle part ailleurs, donc 1.0 doit figurer ici pour
        # que ce chiffre reste traçable.
        numbers=(tam, sam, som, a.reachable_share, a.capturable_share, 1.0),
    )


class UnitAssumptions(BaseModel):
    unit_price: float = Field(gt=0)
    variable_cost_per_unit: float = Field(ge=0)


def unit_margin(a: UnitAssumptions) -> Computation:
    margin = a.unit_price - a.variable_cost_per_unit
    rate = margin / a.unit_price
    return Computation(
        name="marge_unitaire",
        title="Marge unitaire",
        columns=("Poste", "Montant"),
        rows=(
            ("Prix de vente unitaire", _money(a.unit_price)),
            ("Coût variable unitaire", _money(a.variable_cost_per_unit)),
            ("Marge unitaire", _money(margin)),
            ("Taux de marge", _rate(rate)),
        ),
        numbers=(a.unit_price, a.variable_cost_per_unit, margin, rate),
    )


class InvestmentLine(BaseModel):
    label: str
    amount: float = Field(gt=0)
    duration_years: int = Field(gt=0)


class InvestmentAssumptions(BaseModel):
    lines: list[InvestmentLine] = Field(min_length=1)


def investment_table(a: InvestmentAssumptions) -> Computation:
    """Les investissements et leur dotation aux amortissements. La dotation
    alimente le compte de résultat : c'est le seul lien entre les deux
    tableaux, et il doit venir d'ici plutôt que d'être ressaisi."""
    rows = tuple(
        (line.label, _money(line.amount), f"{line.duration_years} ans",
         _money(line.amount / line.duration_years))
        for line in a.lines
    )
    total = sum(line.amount for line in a.lines)
    depreciation = sum(line.amount / line.duration_years for line in a.lines)
    return Computation(
        name="tableau_investissements",
        title="Investissements et amortissements",
        columns=("Poste", "Montant", "Durée", "Dotation annuelle"),
        rows=rows + (("Total", _money(total), "", _money(depreciation)),),
        numbers=(
            tuple(line.amount for line in a.lines)
            + tuple(float(line.duration_years) for line in a.lines)
            + tuple(line.amount / line.duration_years for line in a.lines)
            + (total, depreciation)
        ),
    )


class IncomeAssumptions(BaseModel):
    first_year_revenue: float = Field(gt=0)
    annual_growth: float = Field(ge=-1)
    gross_margin_rate: float = Field(gt=0, le=1)
    fixed_costs: float = Field(ge=0)
    depreciation: float = Field(ge=0)


def income_statement_3y(a: IncomeAssumptions) -> Computation:
    rows, numbers, revenue = [], [], a.first_year_revenue
    for year in range(1, 4):
        margin = revenue * a.gross_margin_rate
        result = margin - a.fixed_costs - a.depreciation
        rows.append((f"Année {year}", _money(revenue), _money(margin),
                     _money(a.fixed_costs), _money(a.depreciation), _money(result)))
        numbers.extend((revenue, margin, result))
        revenue *= 1 + a.annual_growth
    return Computation(
        name="compte_resultat_3ans",
        title="Compte de résultat prévisionnel sur trois ans",
        columns=("Exercice", "Chiffre d'affaires", "Marge brute",
                 "Charges fixes", "Dotations", "Résultat"),
        rows=tuple(rows),
        # Les charges fixes et les dotations s'affichent à chaque exercice sans
        # jamais varier : sans elles ici, une phrase qui les reprend passerait
        # pour un chiffre inventé.
        numbers=tuple(numbers) + (a.fixed_costs, a.depreciation),
    )


class CashAssumptions(BaseModel):
    opening_cash: float
    monthly_inflow: float = Field(ge=0)
    monthly_outflow: float = Field(ge=0)


def cash_plan_12m(a: CashAssumptions) -> Computation:
    """Douze soldes mensuels. Le plus bas est ce que le banquier regarde en
    premier : c'est lui qui dit de combien il faut être financé."""
    rows, numbers, balance = [], [], a.opening_cash
    for month in range(1, 13):
        balance += a.monthly_inflow - a.monthly_outflow
        rows.append((f"Mois {month}", _money(a.monthly_inflow),
                     _money(a.monthly_outflow), _money(balance)))
        numbers.append(balance)
    return Computation(
        name="plan_tresorerie_12mois",
        title="Plan de trésorerie sur douze mois",
        columns=("Mois", "Encaissements", "Décaissements", "Solde de fin de mois"),
        rows=tuple(rows),
        numbers=tuple(numbers) + (a.monthly_inflow, a.monthly_outflow),
    )


class BreakEvenAssumptions(BaseModel):
    fixed_costs: float = Field(ge=0)
    gross_margin_rate: float
    annual_revenue: float | None = None


def _break_even_revenue(a: BreakEvenAssumptions) -> float:
    if a.gross_margin_rate <= 0:
        # Sans cette garde, la division rendrait `inf`, qui s'imprimerait dans
        # le document comme n'importe quel autre nombre.
        raise ValueError("Le taux de marge doit être strictement positif.")
    return a.fixed_costs / a.gross_margin_rate


def break_even_revenue(a: BreakEvenAssumptions) -> Computation:
    threshold = _break_even_revenue(a)
    return Computation(
        name="seuil_rentabilite",
        title="Seuil de rentabilité",
        columns=("Poste", "Montant"),
        rows=(
            ("Charges fixes", _money(a.fixed_costs)),
            ("Taux de marge", _rate(a.gross_margin_rate)),
            ("Chiffre d'affaires nécessaire", _money(threshold)),
        ),
        numbers=(threshold, a.fixed_costs, a.gross_margin_rate),
    )


def break_even_point(a: BreakEvenAssumptions) -> Computation:
    """Le point mort n'est pas le seuil : c'est le moment de l'exercice où il
    est atteint, à chiffre d'affaires régulier. Au-delà de douze, il n'est pas
    atteint dans l'année — et c'est une information, pas une erreur."""
    if a.annual_revenue is None or a.annual_revenue <= 0:
        raise ValueError("Le point mort réclame un chiffre d'affaires annuel positif.")
    threshold = _break_even_revenue(a)
    months = threshold / a.annual_revenue * 12
    reached = "oui" if months <= 12 else "non, au-delà de l'exercice"
    return Computation(
        name="point_mort",
        title="Point mort",
        columns=("Poste", "Valeur"),
        rows=(
            ("Seuil de rentabilité", _money(threshold)),
            ("Chiffre d'affaires annuel prévu", _money(a.annual_revenue)),
            ("Point mort", f"{months:.2f} mois".replace(".", ",")),
            ("Atteint dans l'exercice", reached),
        ),
        numbers=(months, threshold, a.annual_revenue),
    )


class FundingAssumptions(BaseModel):
    investments: float = Field(ge=0)
    working_capital: float = Field(ge=0)
    opening_cash: float = Field(ge=0)
    equity: float = Field(ge=0)
    loan: float = Field(ge=0)
    grants: float = Field(ge=0)
    yearly_cash_flow: list[float] = Field(default_factory=list)
    yearly_loan_repayment: list[float] = Field(default_factory=list)


def initial_funding_plan(a: FundingAssumptions) -> Computation:
    """Besoins contre ressources au démarrage. L'écart est rendu tel quel :
    un plan qui ne s'équilibre pas est une information pour le lecteur, pas
    quelque chose à rattraper en douce."""
    needs = a.investments + a.working_capital + a.opening_cash
    resources = a.equity + a.loan + a.grants
    gap = resources - needs
    return Computation(
        name="plan_financement_initial",
        title="Plan de financement initial",
        columns=("Besoins", "Montant", "Ressources", "Montant"),
        rows=(
            ("Investissements", _money(a.investments), "Apport personnel", _money(a.equity)),
            ("Besoin en fonds de roulement", _money(a.working_capital), "Emprunt", _money(a.loan)),
            ("Trésorerie de départ", _money(a.opening_cash), "Subventions", _money(a.grants)),
            ("Total des besoins", _money(needs), "Total des ressources", _money(resources)),
            ("Écart", "", "", _money(gap)),
        ),
        numbers=(
            needs, resources, gap,
            a.investments, a.working_capital, a.opening_cash,
            a.equity, a.loan, a.grants,
        ),
    )


def funding_plan_3y(a: FundingAssumptions) -> Computation:
    initial_needs = a.investments + a.working_capital + a.opening_cash
    initial_resources = a.equity + a.loan + a.grants
    rows, numbers = [], []
    cash = initial_resources - initial_needs
    for index in range(3):
        cash_flow = a.yearly_cash_flow[index] if index < len(a.yearly_cash_flow) else 0.0
        repayment = (
            a.yearly_loan_repayment[index] if index < len(a.yearly_loan_repayment) else 0.0
        )
        cash += cash_flow - repayment
        rows.append((f"Année {index + 1}", _money(cash_flow), _money(repayment), _money(cash)))
        numbers.extend((cash_flow, repayment, cash))
    return Computation(
        name="plan_financement_3ans",
        title="Plan de financement sur trois ans",
        columns=("Exercice", "Capacité d'autofinancement",
                 "Remboursement d'emprunt", "Trésorerie cumulée"),
        rows=tuple(rows),
        numbers=tuple(numbers),
    )


class LoanAssumptions(BaseModel):
    principal: float = Field(gt=0)
    annual_rate: float = Field(ge=0)
    years: int = Field(gt=0)


def loan_schedule(a: LoanAssumptions) -> Computation:
    """Annuité constante : P·i / (1 − (1+i)^−n), et la division simple quand
    le taux est nul — le cas d'un prêt d'honneur, fréquent à la création."""
    if a.annual_rate == 0:
        annuity = a.principal / a.years
    else:
        annuity = a.principal * a.annual_rate / (1 - (1 + a.annual_rate) ** -a.years)
    rows, balance = [], a.principal
    interests, repayments, balances = [], [], []
    for year in range(1, a.years + 1):
        interest = balance * a.annual_rate
        repaid = annuity - interest
        balance -= repaid
        if year == a.years:
            # Le dernier solde doit tomber sur zéro et non sur un résidu de
            # virgule flottante : le tableau part dans un document bancaire.
            # Mais on regarde avant d'écraser — forcer sans vérifier
            # imprimerait « 0,00 € » même si la formule était fausse de
            # plusieurs milliers d'euros, et aucun test n'y verrait rien.
            if abs(balance) > 0.01:
                raise ValueError(
                    f"l'échéancier ne s'amortit pas : {balance:.2f} € de reste"
                )
            balance = 0.0
        interests.append(interest)
        repayments.append(repaid)
        balances.append(balance)
        rows.append((f"Année {year}", _money(annuity), _money(interest),
                     _money(repaid), _money(balance)))
    return Computation(
        name="annuites_credit",
        title="Échéancier d'emprunt",
        columns=("Exercice", "Annuité", "Intérêts", "Capital remboursé",
                 "Capital restant dû"),
        rows=tuple(rows),
        # Chaque échéance affiche des intérêts, un capital remboursé et un
        # solde qui lui sont propres : sans les listes complètes ici, une
        # phrase qui reprend la troisième annuité passerait pour inventée.
        numbers=(
            (annuity, annuity * a.years, annuity * a.years - a.principal)
            + tuple(interests) + tuple(repayments) + tuple(balances)
        ),
    )


# Les clés sont celles que `bp.yaml` déclare dans `calculs:` — valeurs de
# contrat, donc en français.
COMPUTATIONS: dict[str, Callable[..., Computation]] = {
    "tam_sam_som": market_size,
    "marge_unitaire": unit_margin,
    "tableau_investissements": investment_table,
    "compte_resultat_3ans": income_statement_3y,
    "plan_tresorerie_12mois": cash_plan_12m,
    "seuil_rentabilite": break_even_revenue,
    "point_mort": break_even_point,
    "plan_financement_initial": initial_funding_plan,
    "plan_financement_3ans": funding_plan_3y,
    "annuites_credit": loan_schedule,
}


def run_computation(name: str, assumptions: BaseModel) -> Computation:
    """Point d'entrée unique. Le nœud `calculs` lit les identifiants dans le
    template et passe par ici : il ne connaît aucune des dix fonctions."""
    if name not in COMPUTATIONS:
        raise KeyError(f"calcul inconnu : {name}")
    return COMPUTATIONS[name](assumptions)
