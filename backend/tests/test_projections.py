from uuid import uuid4

import pytest
import pytest_asyncio

from app.agent.projections import (
    SECTION_STATUSES,
    load_facts,
    load_sections,
    mark_for_reopening,
    reproject,
    save_facts,
    save_section,
)
from app.agent.state import Fact, Paragraph, SectionRef
from app.agent.templates import load_catalogue
from app.core.db import connection
from app.projects.repository import create_project

CATALOGUE = load_catalogue()


@pytest_asyncio.fixture
async def project(migrated_db):
    # La connexion se referme avant le `yield`, et non pendant : le pool
    # (`min_size=1`) réouvre à chaque appel de `connection()`, et une
    # connexion gardée ouverte pendant tout le test vide le pool inactif,
    # ce qui bloque le deuxième appel de `connection()` que le corps du
    # test effectue — un interblocage, observé en pratique, pas une
    # hypothèse. Voir le rapport de la tâche 4.
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) "
                "values (%s, 'x', true) returning id",
                (f"agent-{uuid4()}@exemple.fr",),
            )
            user_id = (await cur.fetchone())[0]
        project_id = await create_project(
            conn, user_id, nom="CoachDom", documents="both",
            profil_cdc="consultation", profil_bp="banque",
            thread_id=f"thread-{uuid4()}", templates_version="0.1",
        )
    yield project_id


def test_section_ids_are_unique_across_both_documents():
    # La clé primaire de `sections` est (project_id, section_id) : elle ne
    # porte PAS le document. Deux sections homonymes dans les deux templates
    # s'écraseraient l'une l'autre en base, sans erreur. Aucune collision
    # aujourd'hui ; ce test est ce qui empêche d'en introduire une.
    cdc = {s.id for s in CATALOGUE.cdc.sections}
    bp = {s.id for s in CATALOGUE.bp.sections}
    assert not (cdc & bp), f"identifiants partagés : {sorted(cdc & bp)}"


def test_every_computation_a_template_declares_exists():
    # Croisement que ni la tâche 2 ni la tâche 3 ne pouvaient faire seules.
    from app.agent.finance import COMPUTATIONS

    declares = {c for s in CATALOGUE.bp.sections for c in s.calculs}
    assert declares <= set(COMPUTATIONS), f"calculs sans fonction : {declares - set(COMPUTATIONS)}"


async def test_facts_make_a_round_trip(project):
    facts = {
        "nom_projet": Fact(fact_id="nom_projet", value="CoachDom", source="user"),
        "budget_global": Fact(fact_id="budget_global", value=None, source="user"),
        "type_projet": Fact(fact_id="type_projet", value="plateforme",
                            source="deduced", confidence=0.82),
    }
    async with connection() as conn:
        await save_facts(conn, project, facts)
        reloaded = await load_facts(conn, project)
    assert reloaded == facts


async def test_a_fact_saved_twice_is_updated_not_duplicated(project):
    async with connection() as conn:
        await save_facts(conn, project, {"n": Fact(fact_id="n", value=1, source="deduced")})
        await save_facts(conn, project, {"n": Fact(fact_id="n", value=2, source="user")})
        reloaded = await load_facts(conn, project)
    assert reloaded["n"].value == 2
    assert reloaded["n"].source == "user"


async def test_an_unknown_answer_survives_the_round_trip(project):
    # `value=None` doit se relire comme « l'utilisateur ne sait pas », pas
    # comme un fait absent : c'est ce qui l'empêche d'être redemandé.
    async with connection() as conn:
        await save_facts(conn, project, {"b": Fact(fact_id="b", value=None, source="user")})
        reloaded = await load_facts(conn, project)
    assert "b" in reloaded
    assert reloaded["b"].value is None


async def test_a_section_makes_a_round_trip(project):
    ref = SectionRef(document="cdc", section_id="contexte_objectifs", order=1)
    blocks = [Paragraph(text="Le projet vise à outiller les coachs à domicile.")]
    async with connection() as conn:
        await save_section(conn, project, ref, blocks=blocks, statut="done", note=9, revisions=1)
        sections = await load_sections(conn, project)
    assert len(sections) == 1
    assert sections[0]["section_id"] == "contexte_objectifs"
    assert sections[0]["document"] == "cdc"
    assert sections[0]["note"] == 9
    assert sections[0]["blocks"] == blocks


async def test_sections_come_back_in_production_order(project):
    async with connection() as conn:
        for ref in CATALOGUE.plan_for("cdc", "consultation", None)[:3][::-1]:
            await save_section(conn, project, ref, blocks=[Paragraph(text="x")],
                               statut="done", note=8, revisions=0)
        sections = await load_sections(conn, project)
    assert [s["ordre"] for s in sections] == [1, 2, 3]


async def test_reopening_marks_only_the_named_sections(project):
    plan = CATALOGUE.plan_for("cdc", "consultation", None)[:3]
    async with connection() as conn:
        for ref in plan:
            await save_section(conn, project, ref, blocks=[Paragraph(text="x")],
                               statut="done", note=8, revisions=0)
        touched = await mark_for_reopening(conn, project, {f"cdc.{plan[1].section_id}"})
        sections = {s["section_id"]: s["statut"] for s in await load_sections(conn, project)}
    assert touched == 1
    assert sections[plan[1].section_id] == "reopened"
    assert sections[plan[0].section_id] == "done"


async def test_reprojecting_replaces_what_was_there(project):
    # Le §4.6 : en cas de divergence, le point de reprise gagne et les
    # projections sont réécrites depuis lui.
    ref = SectionRef(document="cdc", section_id="contexte_objectifs", order=1)
    async with connection() as conn:
        await save_facts(conn, project, {"vieux": Fact(fact_id="vieux", value=1, source="user")})
        await save_section(conn, project, ref, blocks=[Paragraph(text="périmé")],
                           statut="done", note=5, revisions=0)
        await reproject(
            conn, project,
            facts={"neuf": Fact(fact_id="neuf", value=2, source="user")},
            sections=[(ref, [Paragraph(text="à jour")], "done", 9, 1)],
        )
        facts = await load_facts(conn, project)
        sections = await load_sections(conn, project)
    assert set(facts) == {"neuf"}
    assert sections[0]["blocks"][0].text == "à jour"
    assert sections[0]["note"] == 9


async def test_projections_of_one_project_never_reach_another(project):
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) "
                "values (%s, 'x', true) returning id", (f"autre-{uuid4()}@exemple.fr",))
            other_user = (await cur.fetchone())[0]
        other = await create_project(
            conn, other_user, nom="Autre", documents="cdc", profil_cdc="cadrage",
            profil_bp=None, thread_id=f"thread-{uuid4()}", templates_version="0.1")
        await save_facts(conn, project, {"a": Fact(fact_id="a", value=1, source="user")})
        assert await load_facts(conn, other) == {}


def test_the_documented_statuses_are_the_only_ones():
    assert SECTION_STATUSES == ("pending", "writing", "done", "reopened")
