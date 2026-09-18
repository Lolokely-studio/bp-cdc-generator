import pytest

from app.agent.finance import BreakEvenAssumptions, run_computation
from app.agent.prompts import (
    Critique,
    ExtractedFacts,
    FoundInconsistencies,
    ProposedQuestions,
    coherence_prompt,
    critique_prompt,
    extraction_prompt,
    parse_written_text,
    questions_prompt,
    writing_prompt,
)
from app.agent.state import BulletList, Fact, Paragraph, Placeholder, Table
from app.agent.templates import load_catalogue

CATALOGUE = load_catalogue()
SECTION = CATALOGUE.section("cdc.contexte_objectifs")
THRESHOLD = run_computation("seuil_rentabilite", BreakEvenAssumptions(
    fixed_costs=120_000, gross_margin_rate=0.65,
))


def _render(messages):
    return "\n".join(m.content for m in messages)


def test_the_writing_prompt_carries_the_section_instructions_verbatim():
    # Les consignes sont le fruit de l'analyse des templates : les paraphraser
    # dans le code ferait diverger deux formulations de la même règle.
    messages = writing_prompt(SECTION, facts={}, computations=[], profil="consultation")
    rendered = _render(messages)
    assert SECTION.consignes.strip() in rendered
    assert SECTION.objectif.strip() in rendered
    assert SECTION.longueur_cible in rendered


def test_the_writing_prompt_names_the_profile():
    # Les consignes portent des clauses « Profil consultation : … ». Sans le
    # profil, le modèle ne sait pas laquelle appliquer.
    assert "consultation" in _render(
        writing_prompt(SECTION, facts={}, computations=[], profil="consultation"))


def test_the_writing_prompt_lists_the_facts_with_their_labels():
    facts = {"nom_projet": Fact(fact_id="nom_projet", value="CoachDom", source="user")}
    rendered = _render(writing_prompt(SECTION, facts=facts, computations=[], profil="cadrage"))
    assert "CoachDom" in rendered
    assert CATALOGUE.fact("nom_projet").libelle in rendered


def test_an_unknown_fact_is_presented_as_an_assumption_to_declare():
    # « Je ne sais pas » est une valeur : le texte doit l'assumer, pas
    # l'ignorer ni inventer.
    facts = {"budget_global": Fact(fact_id="budget_global", value=None, source="user")}
    rendered = _render(writing_prompt(SECTION, facts=facts, computations=[], profil="cadrage"))
    assert "budget_global" in rendered or CATALOGUE.fact("budget_global").libelle in rendered
    assert "hypothèse" in rendered.lower()


def test_the_writing_prompt_offers_the_tables_by_name_not_by_content():
    rendered = _render(writing_prompt(SECTION, facts={}, computations=[THRESHOLD], profil="cadrage"))
    assert "[Tableau: seuil_rentabilite]" in rendered
    # Les chiffres du tableau n'ont rien à faire dans le prompt : le modèle
    # les recopierait, et un chiffre recopié est un chiffre qui peut fauter.
    assert "184" not in rendered


def test_the_critique_prompt_is_the_grid_and_nothing_else():
    rendered = _render(critique_prompt(SECTION, [Paragraph(text="Un brouillon.")]))
    for critere in SECTION.grille:
        assert critere in rendered


def test_the_questions_prompt_carries_the_default_wording():
    manquants = ["nom_projet", "objectifs_mesurables"]
    rendered = _render(questions_prompt(SECTION, manquants, CATALOGUE))
    assert CATALOGUE.fact("nom_projet").question in rendered


def test_the_extraction_prompt_only_offers_deducible_facts():
    # Un fait non déductible ne peut qu'être demandé : le proposer à
    # l'extraction inviterait le modèle à l'inventer.
    definitions = [CATALOGUE.fact(f) for f in ("nom_projet", "date_lancement_visee")]
    rendered = _render(extraction_prompt("Une plateforme de coaching.", definitions))
    assert "nom_projet" in rendered
    assert "date_lancement_visee" not in rendered


def test_the_coherence_prompt_spans_both_documents():
    rendered = _render(coherence_prompt([
        ("cdc.contexte_objectifs", [Paragraph(text="Le budget est de 60 000 €.")]),
        ("bp.compte_resultat", [Paragraph(text="Le budget est de 45 000 €.")]),
    ]))
    assert "cdc.contexte_objectifs" in rendered and "bp.compte_resultat" in rendered


# ---------- relecture du texte produit ----------

def test_paragraphs_are_separated_by_blank_lines():
    blocks = parse_written_text("Premier paragraphe.\n\nSecond paragraphe.", [])
    assert blocks == [Paragraph(text="Premier paragraphe."), Paragraph(text="Second paragraphe.")]


def test_a_paragraph_keeps_its_internal_line_breaks_as_spaces():
    blocks = parse_written_text("Une phrase\ncoupée en deux.", [])
    assert blocks == [Paragraph(text="Une phrase coupée en deux.")]


def test_dashed_lines_become_a_list():
    blocks = parse_written_text("- Premier point\n- Deuxième point", [])
    assert blocks == [BulletList(items=["Premier point", "Deuxième point"])]


def test_a_placeholder_is_its_own_block():
    blocks = parse_written_text("[Donnée à compléter : source]", [])
    assert blocks == [Placeholder(label="source")]


def test_a_table_marker_pulls_the_computation_in():
    blocks = parse_written_text("Voici le seuil.\n\n[Tableau: seuil_rentabilite]", [THRESHOLD])
    assert isinstance(blocks[1], Table)
    assert blocks[1].title == THRESHOLD.title
    assert blocks[1].rows == [list(r) for r in THRESHOLD.rows]


def test_tables_are_numbered_in_order_of_appearance():
    other = run_computation("seuil_rentabilite", BreakEvenAssumptions(
        fixed_costs=1, gross_margin_rate=0.5))
    blocks = parse_written_text(
        "[Tableau: seuil_rentabilite]\n\nDu texte.\n\n[Tableau: seuil_rentabilite]",
        [THRESHOLD, other],
    )
    assert [b.number for b in blocks if isinstance(b, Table)] == [1, 2]


def test_a_table_marker_without_its_computation_is_refused():
    # Mieux vaut échouer ici — la section repart, le modèle recommence — que
    # produire un document avec un trou silencieux à la place d'un tableau.
    with pytest.raises(ValueError):
        parse_written_text("[Tableau: inexistant]", [])


def test_a_mixed_section_keeps_its_order():
    text = (
        "Le dispositif couvre trois usages.\n\n"
        "- Le premier\n- Le deuxième\n\n"
        "[Donnée à compléter : volumétrie]\n\n"
        "Conclusion."
    )
    assert [b.kind for b in parse_written_text(text, [])] == [
        "paragraph", "list", "placeholder", "paragraph",
    ]


def test_an_empty_answer_yields_no_blocks():
    assert parse_written_text("   \n\n  ", []) == []


# ---------- schémas de sortie ----------

def test_the_output_schemas_are_the_shape_the_nodes_expect():
    assert ExtractedFacts(facts=[
        {"fact_id": "nom_projet", "value": "CoachDom", "confidence": 0.9},
    ]).facts[0].fact_id == "nom_projet"
    assert ProposedQuestions(questions=[
        {"fact_id": "budget_global", "question": "Quel budget ?"},
    ]).questions[0].fact_id == "budget_global"
    assert Critique(score=7, problems=["Un objectif n'est pas mesurable."]).score == 7
    assert FoundInconsistencies(inconsistencies=[]).inconsistencies == []


def test_a_critique_score_outside_the_scale_is_refused():
    with pytest.raises(ValueError):
        Critique(score=11, problems=[])


def test_the_format_example_cannot_be_mistaken_for_a_computation():
    # Le mot d'exemple de la consigne était un identifiant valide. Un modèle
    # qui recopie l'exemple — le simulé le fait — demandait alors un tableau
    # qui n'existe pas, et l'analyseur levait.
    from app.agent.prompts import WRITING_FORMAT, _TABLE

    for line in WRITING_FORMAT.splitlines():
        assert not _TABLE.match(line.strip()), f"l'exemple passe pour un repère : {line}"
