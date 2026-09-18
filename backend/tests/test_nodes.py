from uuid import uuid4

import pytest
import pytest_asyncio

from app.agent import nodes
from app.agent.state import Fact, Paragraph, SectionRef
from app.agent.templates import load_catalogue
from app.core.db import connection
from app.llm.fake import FakeTransport
from app.projects.repository import create_project

CATALOGUE = load_catalogue()


@pytest_asyncio.fixture
async def project(migrated_db):
    # Les nœuds qui appellent le modèle écrivent dans `llm_usage`, et `save`
    # dans `facts`/`sections` : les trois portent une clé étrangère vers
    # `projects`. Le brief teste ces nœuds avec un UUID constant qui ne
    # désigne aucune ligne, ce qui échoue avec une `ForeignKeyViolation` —
    # défaut documenté dans le rapport. La correction reprend le motif de
    # `tests/test_projections.py::project` : une vraie ligne, effacée avec la
    # base jetable entre les runs.
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) "
                "values (%s, 'x', true) returning id",
                (f"nodes-{uuid4()}@exemple.fr",),
            )
            user_id = (await cur.fetchone())[0]
        project_id = await create_project(
            conn, user_id, nom="CoachDom", documents="both",
            profil_cdc="consultation", profil_bp="banque",
            thread_id=f"thread-{uuid4()}", templates_version="0.1",
        )
    yield str(project_id)


def _state(**surcharges):
    base = {
        "project_id": "00000000-0000-0000-0000-000000000001",
        "documents": "both",
        "profil_cdc": "consultation",
        "profil_bp": "banque",
        "idea": "Une plateforme de coaching sportif à domicile.",
        "facts": {},
        "plan": CATALOGUE.plan_for("both", "consultation", "banque"),
        "cursor": 0,
        "draft": None,
        "score": None,
        "problems": [],
        "revisions": 0,
        "question_rounds": 0,
        "computations": {},
        "inconsistencies": [],
    }
    return {**base, **surcharges}


# ---------- routage, pur et sans base ----------

def test_missing_required_facts_send_us_to_the_questions():
    assert nodes.route_after_gaps(_state()) == "formulate_questions"


def test_two_rounds_of_questions_are_enough():
    # Le §4.4 plafonne à deux tours : au-delà, on rédige avec ce qu'on a et
    # les manques deviennent des données à compléter. Sans ce plafond, un
    # projet mal renseigné tournerait en rond.
    assert nodes.route_after_gaps(_state(question_rounds=2)) != "formulate_questions"


def test_a_section_declaring_computations_goes_through_them():
    plan = CATALOGUE.plan_for("bp", None, "banque")
    index = next(i for i, r in enumerate(plan)
                 if CATALOGUE.section(f"bp.{r.section_id}").calculs)
    state = _state(documents="bp", profil_cdc=None, plan=plan, cursor=index,
                 question_rounds=2, facts=_required_facts(plan[index]))
    assert nodes.route_after_gaps(state) == "compute"


def test_a_section_without_computations_goes_straight_to_writing():
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    state = _state(documents="cdc", profil_bp=None, plan=plan, cursor=0,
                 question_rounds=2, facts=_required_facts(plan[0]))
    assert nodes.route_after_gaps(state) == "write"


def _required_facts(ref: SectionRef) -> dict[str, Fact]:
    section = CATALOGUE.section(f"{ref.document}.{ref.section_id}")
    return {f: Fact(fact_id=f, value="une valeur", source="user") for f in section.faits_requis}


def test_an_orphan_number_sends_the_section_back_to_writing():
    assert nodes.route_after_numbers(_state(problems=["chiffre orphelin : 2 400 000 000"])) == "write"


def test_two_revisions_are_enough_even_with_an_orphan():
    state = _state(problems=["chiffre orphelin : 2 400 000 000"], revisions=2)
    assert nodes.route_after_numbers(state) == "critique"


def test_a_low_score_rewrites_then_wakes_the_user():
    # Les deux seuils font deux choses différentes : sous 7 la machine
    # réécrit, sous 8 après cela elle réveille l'utilisateur.
    assert nodes.route_after_critique(_state(score=6)) == "write"
    assert nodes.route_after_critique(_state(score=6, revisions=2)) == "review"
    assert nodes.route_after_critique(_state(score=7, revisions=2)) == "review"


def test_a_high_score_saves_without_stopping():
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    index = next(i for i, r in enumerate(plan)
                 if CATALOGUE.section(f"cdc.{r.section_id}").validation == "si_note_basse")
    assert nodes.route_after_critique(_state(plan=plan, cursor=index, score=9)) == "save"


def test_a_section_that_always_validates_stops_whatever_the_score():
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    index = next(i for i, r in enumerate(plan)
                 if CATALOGUE.section(f"cdc.{r.section_id}").validation == "toujours")
    assert nodes.route_after_critique(_state(plan=plan, cursor=index, score=10)) == "review"


def test_the_run_moves_on_until_the_plan_is_exhausted():
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    assert nodes.route_after_save(_state(plan=plan, cursor=1)) == "analyse_gaps"
    assert nodes.route_after_save(_state(plan=plan, cursor=len(plan))) == "coherence_check"


# ---------- nœuds appelant le modèle, avec le simulé ----------

async def test_extraction_only_keeps_deducible_facts(project):
    maj = await nodes.extract_facts(_state(project_id=project), transport=FakeTransport())
    assert set(maj) == {"facts"}
    for fact in maj["facts"].values():
        assert CATALOGUE.fact(fact.fact_id).deductible
        assert fact.source == "deduced"


async def test_writing_produces_blocks(project):
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    maj = await nodes.write(_state(project_id=project, plan=plan, cursor=0),
                            transport=FakeTransport())
    assert maj["draft"]
    assert all(hasattr(b, "kind") for b in maj["draft"])
    assert maj["revisions"] == 1


async def test_the_critique_returns_a_score_on_ten(project):
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    state = _state(project_id=project, plan=plan, cursor=0,
                   draft=[Paragraph(text="Un brouillon.")])
    maj = await nodes.critique(state, transport=FakeTransport())
    assert 0 <= maj["score"] <= 10


async def test_checking_numbers_needs_no_model():
    # Aucun transport n'est passé : ce nœud est déterministe, et le lui
    # rappeler par sa signature vaut mieux que par un commentaire.
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    state = _state(plan=plan, cursor=0,
                 draft=[Paragraph(text="Un marché de 2 400 000 000 €.")])
    maj = await nodes.check_numbers(state)
    assert maj["problems"]
    assert "2 400 000 000" in maj["problems"][0]


async def test_computations_run_from_the_template_alone():
    plan = CATALOGUE.plan_for("bp", None, "banque")
    index = next(i for i, r in enumerate(plan)
                 if "seuil_rentabilite" in CATALOGUE.section(f"bp.{r.section_id}").calculs)
    # `compute` associe un fait à un champ d'hypothèse par égalité stricte de
    # nom (`field_name in state["facts"]`, voir `nodes.compute`). Le brief
    # utilisait ici des identifiants français plausibles mais absents du
    # catalogue (`charges_fixes_annuelles`, `taux_marge_brute`), qui ne
    # matchaient ni le catalogue ni les noms de champs anglais de
    # `BreakEvenAssumptions` (`fixed_costs`, `gross_margin_rate`) : le calcul
    # ne recevait jamais d'hypothèses et `compute` le sautait toujours,
    # silencieusement. Défaut documenté dans le rapport ; corrigé ici en
    # nommant les faits comme le modèle d'hypothèses les attend.
    facts = {
        "fixed_costs": Fact(fact_id="fixed_costs", value=120_000, source="user"),
        "gross_margin_rate": Fact(fact_id="gross_margin_rate", value=0.65, source="user"),
    }
    maj = await nodes.compute(_state(documents="bp", profil_cdc=None, plan=plan,
                                    cursor=index, facts=facts))
    assert "seuil_rentabilite" in maj["computations"]


async def test_saving_advances_the_cursor_and_writes_the_projection(project):
    # La projection est écrite par le nœud, le point de reprise reste la
    # source de vérité (§4.6).
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    state = _state(project_id=project, plan=plan, cursor=0,
                   draft=[Paragraph(text="Un texte.")], score=9)
    maj = await nodes.save(state)
    assert maj["cursor"] == 1
    assert maj["draft"] is None
    assert maj["revisions"] == 0
    assert maj["problems"] == []
