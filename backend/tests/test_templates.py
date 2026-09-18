import pytest

from app.agent.templates import (
    Catalogue,
    DocumentTemplate,
    FactDefinition,
    SectionTemplate,
    load_catalogue,
)

CATALOGUE = load_catalogue()


def _minimal_document(document: str, sections: list[SectionTemplate]) -> DocumentTemplate:
    return DocumentTemplate(
        version="0.1",
        statut="brouillon",
        seuil_relecture=8,
        document=document,
        profils_disponibles={"profil": "test"},
        sections=sections,
    )


def _minimal_section(section_id: str, faits_requis: list[str]) -> SectionTemplate:
    return SectionTemplate(
        id=section_id,
        titre="Section de test",
        ordre=1,
        ordre_lecture=1,
        profils=["profil"],
        validation="toujours",
        objectif="Objectif de test.",
        longueur_cible="100 mots",
        faits_requis=faits_requis,
        consignes="Consignes de test.",
        grille=["Critère de test"],
    )


def test_the_two_documents_carry_fifteen_sections_each():
    assert len(CATALOGUE.cdc.sections) == 15
    assert len(CATALOGUE.bp.sections) == 15


def test_the_fact_catalogue_is_complete():
    assert len(CATALOGUE.facts) == 74


def test_utilise_par_is_exactly_the_inverse_of_what_sections_declare():
    # L'invariant du catalogue. `utilise_par` est un champ DÉRIVÉ : écrit à la
    # main, il dérive au premier changement de section, et la dérive ne se voit
    # nulle part — elle fait poser une question inutile, ou n'en fait pas poser
    # une nécessaire. Ce test est la seule chose qui l'empêche.
    derive = CATALOGUE.derived_utilise_par()
    ecrit = {fact_id: set(f.utilise_par) for fact_id, f in CATALOGUE.facts.items()}
    assert derive == ecrit, (
        "Régénérer `utilise_par` dans catalogue-faits.yaml : "
        f"en trop {[(k, ecrit[k] - derive.get(k, set())) for k in ecrit if ecrit[k] - derive.get(k, set())]}, "
        f"manquants {[(k, derive[k] - ecrit.get(k, set())) for k in derive if derive[k] - ecrit.get(k, set())]}"
    )


def test_derived_utilise_par_seeds_a_key_for_a_fact_no_section_uses():
    # Garde-fou du correctif : un fait catalogué mais pas encore cité par une
    # section doit apparaître dans le dérivé avec un ensemble vide. Sans
    # amorce sur tous les faits, la clé manquerait côté dérivé tandis que
    # l'écrit la porterait à `set()`, et l'égalité de dictionnaires échouerait
    # pour une différence que le message d'erreur ne saurait pas montrer.
    catalogue = Catalogue(
        cdc=_minimal_document("cdc", [_minimal_section("section_test", ["fait_utilise"])]),
        bp=_minimal_document("bp", []),
        facts={
            "fait_utilise": FactDefinition(
                id="fait_utilise", libelle="Utilisé", type="texte_court", question="?"
            ),
            "fait_orphelin": FactDefinition(
                id="fait_orphelin", libelle="Orphelin", type="texte_court", question="?"
            ),
        },
    )
    derive = catalogue.derived_utilise_par()
    assert derive["fait_orphelin"] == set()
    assert derive["fait_utilise"] == {"cdc.section_test"}


@pytest.mark.parametrize("document", ["cdc", "bp"])
def test_every_fact_a_section_asks_for_exists(document):
    template = getattr(CATALOGUE, document)
    unknown = {
        fact_id
        for section in template.sections
        for fact_id in (*section.faits_requis, *section.faits_utiles)
        if fact_id not in CATALOGUE.facts
    }
    assert not unknown, f"{document} réclame des faits absents du catalogue : {unknown}"


@pytest.mark.parametrize("document", ["cdc", "bp"])
def test_dependencies_name_sections_of_the_same_document(document):
    # Constaté dans les fichiers : aucune dépendance ne franchit la frontière
    # entre les deux documents. C'est ce qui autorise à rédiger le cahier des
    # charges entièrement avant le business plan.
    template = getattr(CATALOGUE, document)
    known_ids = {s.id for s in template.sections}
    for section in template.sections:
        assert set(section.depend_de) <= known_ids, section.id


@pytest.mark.parametrize("document", ["cdc", "bp"])
def test_orders_are_a_permutation_of_one_to_fifteen(document):
    template = getattr(CATALOGUE, document)
    assert sorted(s.ordre for s in template.sections) == list(range(1, 16))
    assert sorted(s.ordre_lecture for s in template.sections) == list(range(1, 16))


def test_the_business_plan_summary_is_written_last_and_read_first():
    last = max(CATALOGUE.bp.sections, key=lambda s: s.ordre)
    assert last.ordre_lecture == 1


def test_a_plan_for_both_documents_holds_thirty_sections():
    plan = CATALOGUE.plan_for("both", "consultation", "banque")
    assert len(plan) == 30
    assert [ref.order for ref in plan] == list(range(1, 31))
    # Le cahier des charges d'abord, entièrement, puis le business plan.
    assert [ref.document for ref in plan] == ["cdc"] * 15 + ["bp"] * 15


def test_a_plan_for_one_document_holds_only_that_one():
    plan = CATALOGUE.plan_for("bp", None, "investisseur")
    assert {ref.document for ref in plan} == {"bp"}
    assert len(plan) == 15


def test_a_profile_removes_the_sections_it_does_not_call_for():
    consultation = CATALOGUE.plan_for("cdc", "consultation", None)
    cadrage = CATALOGUE.plan_for("cdc", "cadrage", None)
    # Le profil cadrage est un document interne : pas de cadre de réponse, pas
    # de modalités de consultation.
    assert len(cadrage) <= len(consultation)
    assert {r.section_id for r in cadrage} <= {r.section_id for r in consultation}


def test_a_plan_without_a_profile_for_a_requested_document_is_refused():
    with pytest.raises(ValueError):
        CATALOGUE.plan_for("both", None, "banque")


def test_sections_using_a_fact_covers_required_and_useful_alike():
    # « Un fait n'est demandé qu'une seule fois, même s'il sert les deux
    # documents » : c'est `utilise_par` qui porte cette garantie, et il ne
    # distingue pas requis d'utile.
    users = CATALOGUE.sections_using("nom_projet")
    assert "cdc.contexte_objectifs" in users
    assert "bp.probleme_solution" in users


def test_changing_a_fact_reopens_the_sections_that_use_it_and_only_those():
    # Troisième invariant du §4.2. Il vit ici et non dans le réducteur : il
    # suppose de connaître les templates, qu'un réducteur LangGraph n'a pas à
    # charger à chaque mise à jour de l'état.
    to_reopen = CATALOGUE.sections_to_reopen({"nom_projet"})
    assert to_reopen == CATALOGUE.sections_using("nom_projet")
    assert CATALOGUE.sections_to_reopen(set()) == set()


def test_changing_two_facts_unions_their_sections():
    both = CATALOGUE.sections_to_reopen({"nom_projet", "type_projet"})
    assert both == CATALOGUE.sections_using("nom_projet") | CATALOGUE.sections_using("type_projet")


def test_the_review_threshold_comes_from_the_templates():
    # Les deux seuils du §4.4 sont un réglage, pas une constante du code.
    assert CATALOGUE.review_threshold == 8


def test_validation_only_takes_the_two_documented_values():
    values = {s.validation for doc in (CATALOGUE.cdc, CATALOGUE.bp) for s in doc.sections}
    assert values <= {"toujours", "si_note_basse"}


def test_every_section_carries_instructions_and_a_grid():
    # Les prompts sont assemblés depuis ces deux champs : une section qui en
    # manquerait produirait un prompt vide sans que rien ne le dise.
    for document in (CATALOGUE.cdc, CATALOGUE.bp):
        for section in document.sections:
            assert section.consignes.strip(), section.id
            assert section.grille, section.id
            assert section.objectif.strip(), section.id


def test_the_pivot_flag_is_loaded_without_being_interpreted():
    # Champ présent dans le catalogue mais décrit nulle part. On le porte pour
    # ne pas le perdre ; aucun comportement ne s'y adosse tant que sa
    # sémantique n'est pas tranchée.
    pivots = {fact_id for fact_id, f in CATALOGUE.facts.items() if f.pivot}
    assert pivots == {"date_lancement_visee", "budget_developpement", "perimetre_inclus"}


def test_the_catalogue_is_loaded_once():
    assert load_catalogue() is CATALOGUE
