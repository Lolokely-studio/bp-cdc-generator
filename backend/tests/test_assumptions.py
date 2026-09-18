import pytest

from app.agent.assumptions import BUILDERS, build_assumptions
from app.agent.facts import Fact
from app.agent.finance import COMPUTATIONS, run_computation
from app.agent.templates import load_catalogue


def _facts(**values) -> dict[str, Fact]:
    return {k: Fact(fact_id=k, value=v, source="user") for k, v in values.items()}


COMPLETE = _facts(
    prix_moyen_unite=45,
    cout_variable_unitaire=15,
    volume_ventes_an1=4_000,
    charges_fixes_mensuelles=3_000,
    masse_salariale_an1=60_000,
    hypothese_croissance=0.30,
    investissements_initiaux=20_000,
    budget_developpement=40_000,
    tresorerie_securite=15_000,
    apport_fondateurs=30_000,
    emprunt_montant=50_000,
    emprunt_duree=60,
    taux_interet_emprunt=0.04,
    aides_subventions=4_000,
    delai_paiement_clients=30,
    taille_marche_tam=300_000_000,
    taille_marche_sam=90_000_000,
    taille_marche_som=4_500_000,
)


def test_every_computation_has_a_builder():
    # Le défaut d'origine : un calcul sans pont vers les faits est un tableau
    # qui ne sortira jamais, sans que rien ne le dise.
    assert set(BUILDERS) == set(COMPUTATIONS)


@pytest.mark.parametrize("name", sorted(COMPUTATIONS))
def test_a_complete_project_feeds_every_computation(name):
    assumptions = build_assumptions(name, COMPLETE)
    assert assumptions is not None, f"{name} n'a pas trouvé ses hypothèses"
    result = run_computation(name, assumptions)
    assert result.rows


@pytest.mark.parametrize("name", sorted(COMPUTATIONS))
def test_no_facts_means_no_computation(name):
    assert build_assumptions(name, {}) is None


def test_annual_fixed_costs_combine_the_two_facts():
    # 3 000 par mois plus 60 000 de masse salariale : le catalogue les demande
    # séparément parce que c'est ainsi qu'on les connaît.
    assumptions = build_assumptions("seuil_rentabilite", COMPLETE)
    assert assumptions.fixed_costs == pytest.approx(96_000)


def test_the_margin_rate_is_deduced_from_the_price_and_the_variable_cost():
    assumptions = build_assumptions("seuil_rentabilite", COMPLETE)
    assert assumptions.gross_margin_rate == pytest.approx((45 - 15) / 45)


def test_a_percentage_typed_as_thirty_five_is_read_as_a_fraction():
    # L'utilisateur tape « 30 », pas « 0,30 ». Le refuser serait pédant.
    facts = {**COMPLETE, **_facts(hypothese_croissance=30)}
    assert build_assumptions("compte_resultat_3ans", facts).annual_growth == pytest.approx(0.30)


def test_a_loan_duration_in_months_becomes_years():
    # Le catalogue demande des mois, l'échéancier raisonne en années.
    assert build_assumptions("annuites_credit", COMPLETE).years == 5


def test_a_loan_without_a_rate_produces_no_schedule():
    # La décision du propriétaire : plutôt pas de tableau qu'un taux inventé.
    facts = {k: v for k, v in COMPLETE.items() if k != "taux_interet_emprunt"}
    assert build_assumptions("annuites_credit", facts) is None


def test_an_unknown_answer_counts_as_missing():
    # « Je ne sais pas » est une réponse, mais on ne calcule pas dessus.
    facts = {**COMPLETE, "emprunt_montant": Fact(
        fact_id="emprunt_montant", value=None, source="user")}
    assert build_assumptions("annuites_credit", facts) is None


@pytest.mark.parametrize(("libelle", "surcharge", "attendu"), [
    ("un investissement inconnu retire le plan", {"investissements_initiaux": None}, None),
    ("un délai client inconnu retire le plan", {"delai_paiement_clients": None}, None),
    ("un emprunt inconnu retire le plan", {"emprunt_montant": None}, None),
    ("un investissement nul et assumé le garde", {"investissements_initiaux": 0}, "produit"),
])
def test_an_unanswered_required_fact_withholds_the_plan(libelle, surcharge, attendu):
    """La distinction qui manquait : « je ne sais pas » n'est pas zéro.

    Une première version écrivait `or 0.0` et produisait un plan de financement
    qui s'équilibrait en comptant un besoin inconnu pour zéro. Le document part
    à la banque : mieux vaut pas de tableau qu'un tableau faux.
    """
    facts = {**COMPLETE}
    for fact_id, value in surcharge.items():
        facts[fact_id] = Fact(fact_id=fact_id, value=value, source="user")
    result = build_assumptions("plan_financement_initial", facts)
    assert (result is None) == (attendu is None)


@pytest.mark.parametrize("absent", ["emprunt_montant", "aides_subventions", "budget_developpement"])
def test_a_question_never_asked_reads_as_zero(absent):
    """L'autre moitié de la règle, et la moitié qu'une première correction
    avait cassée.

    Un projet sans emprunt, sans subvention ou sans budget de développement
    est un projet ordinaire — un restaurant, un commerce — et la clé peut
    simplement ne pas être là. Les trois sont `faits_utiles` et non
    `faits_requis` dans les templates, et la consigne du budget de
    développement écrit « s'il est fourni ».
    """
    facts = {k: v for k, v in COMPLETE.items() if k != absent}
    assumptions = build_assumptions("plan_financement_initial", facts)
    assert assumptions is not None, f"un projet sans {absent} perd son plan de financement"


def test_a_project_without_a_development_budget_keeps_its_income_statement():
    # Le chemin que la sur-correction retirait : l'amortissement passe par
    # `_investments`, donc le compte de résultat disparaissait avec lui.
    facts = {k: v for k, v in COMPLETE.items() if k != "budget_developpement"}
    assumptions = build_assumptions("compte_resultat_3ans", facts)
    assert assumptions is not None
    # 20 000 d'investissement initial seul, amorti sur trois ans.
    assert assumptions.depreciation == pytest.approx(20_000 / 3)


def test_the_working_capital_comes_from_the_payment_delay():
    # 45 x 4 000 = 180 000 de chiffre d'affaires, 30 jours de délai : un mois.
    assumptions = build_assumptions("plan_financement_initial", COMPLETE)
    assert assumptions.working_capital == pytest.approx(180_000 / 12)


def test_every_fact_id_read_by_a_builder_exists_in_the_catalogue():
    # Une faute de frappe dans un identifiant de fait ferait échouer le
    # constructeur en silence, pour toujours : `_value` rend `None` pour un
    # identifiant inconnu exactement comme pour un fait absent, donc rien ne
    # distingue « le porteur n'a pas répondu » de « le code a mal orthographié
    # la question ». Le brief proposait de scanner le texte source du module
    # par expression régulière ; en pratique cette regex ne matche jamais un
    # seul appel de `_value`/`_rate` (les identifiants sont passés en
    # deuxième argument positionnel, pas suivis d'une parenthèse fermante
    # immédiate), donc le test passait toujours sans rien vérifier — voir le
    # rapport. On vérifie ici directement, par inspection des fermetures
    # (`__closure__`) des fonctions `BUILDERS`, que chaque identifiant en
    # dur qu'elles utilisent existe dans le catalogue chargé.
    import ast
    import inspect

    import app.agent.assumptions as module

    catalogue_ids = set(load_catalogue().facts)
    tree = ast.parse(inspect.getsource(module))
    referenced_ids: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = getattr(node.func, "id", None)
            if func_name in {"_value", "_rate"}:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        referenced_ids.add(arg.value)

    # Le module référence bien des identifiants (sinon le test ne prouverait
    # rien) et chacun existe dans le catalogue.
    assert referenced_ids
    for fact_id in referenced_ids:
        assert fact_id in catalogue_ids, f"identifiant de fait inconnu : {fact_id}"
