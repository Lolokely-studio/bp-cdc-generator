from app.agent.facts import merge_facts
from app.agent.state import Fact


def _user(fact_id: str, value):
    return Fact(fact_id=fact_id, value=value, source="user")


def _deduced(fact_id: str, value, confidence: float = 0.8):
    return Fact(fact_id=fact_id, value=value, source="deduced", confidence=confidence)


def test_a_deduction_never_overwrites_an_answer():
    # Premier invariant du §4.2. C'est la règle qui rend l'extraction sans
    # danger : elle peut se tromper sans effacer ce que l'utilisateur a dit.
    current = {"nom_projet": _user("nom_projet", "CoachDom")}
    merged = merge_facts(current, {"nom_projet": _deduced("nom_projet", "Coach à domicile")})
    assert merged["nom_projet"].value == "CoachDom"
    assert merged["nom_projet"].source == "user"


def test_an_answer_overwrites_a_deduction():
    current = {"nom_projet": _deduced("nom_projet", "Coach à domicile")}
    merged = merge_facts(current, {"nom_projet": _user("nom_projet", "CoachDom")})
    assert merged["nom_projet"].value == "CoachDom"
    assert merged["nom_projet"].source == "user"


def test_an_answer_overwrites_an_answer():
    # L'utilisateur doit pouvoir se corriger.
    current = {"budget_global": _user("budget_global", 50_000)}
    merged = merge_facts(current, {"budget_global": _user("budget_global", 65_000)})
    assert merged["budget_global"].value == 65_000


def test_a_deduction_fills_a_fact_nobody_has_touched():
    merged = merge_facts({}, {"type_projet": _deduced("type_projet", "plateforme")})
    assert merged["type_projet"].value == "plateforme"


def test_i_do_not_know_is_a_value_and_not_an_absence():
    # Deuxième invariant du §4.2. Sans cette protection, l'extraction
    # remplirait un champ que l'utilisateur a explicitement laissé vide, et la
    # question reviendrait au tour suivant.
    current = {"budget_global": _user("budget_global", None)}
    merged = merge_facts(current, {"budget_global": _deduced("budget_global", 40_000)})
    assert merged["budget_global"].value is None
    assert merged["budget_global"].source == "user"


def test_zero_and_false_are_values_not_absences():
    # `if fact.value:` au lieu de `is not None` ferait disparaître ces deux-là.
    current = {"apport_personnel": _user("apport_personnel", 0), "a_des_clients": _user("a_des_clients", False)}
    merged = merge_facts(current, {
        "apport_personnel": _deduced("apport_personnel", 15_000),
        "a_des_clients": _deduced("a_des_clients", True),
    })
    assert merged["apport_personnel"].value == 0
    assert merged["a_des_clients"].value is False


def test_the_reducer_leaves_its_inputs_alone():
    # LangGraph l'appelle à chaque mise à jour de l'état et réutilise les
    # dictionnaires : muter l'entrée corromprait les points de reprise déjà
    # écrits.
    current = {"nom_projet": _user("nom_projet", "CoachDom")}
    incoming = {"type_projet": _deduced("type_projet", "plateforme")}
    merged = merge_facts(current, incoming)
    assert current == {"nom_projet": _user("nom_projet", "CoachDom")}
    assert incoming == {"type_projet": _deduced("type_projet", "plateforme")}
    assert merged is not current


def test_merging_nothing_changes_nothing():
    current = {"nom_projet": _user("nom_projet", "CoachDom")}
    assert merge_facts(current, {}) == current
