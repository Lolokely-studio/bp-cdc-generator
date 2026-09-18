from uuid import uuid4

import pytest
import pytest_asyncio
from langgraph.types import Command

from app.agent.checkpointer import close_checkpointer, purge_checkpoints
from app.agent.graph import build_graph, compiled_graph, initial_state
from app.agent.projections import load_sections
from app.core.db import connection
from app.projects.repository import create_project


@pytest_asyncio.fixture
async def project(migrated_db, monkeypatch):
    # Le graphe ne reçoit pas de transport : la passerelle lit le réglage.
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config
    config.settings.cache_clear()
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) "
                "values (%s, 'x', true) returning id", (f"g-{uuid4()}@exemple.fr",))
            user_id = (await cur.fetchone())[0]
        project_id = await create_project(
            conn, user_id, nom="CoachDom", documents="cdc",
            profil_cdc="cadrage", profil_bp=None,
            thread_id=f"thread-{uuid4()}", templates_version="0.1")
    yield project_id
    await close_checkpointer()
    config.settings.cache_clear()


def test_the_graph_compiles_with_every_edge_of_the_spec():
    graph = build_graph().compile()
    node_names = set(graph.get_graph().nodes)
    assert {"extract_facts", "analyse_gaps", "formulate_questions", "ask_questions",
            "compute", "write", "check_numbers", "critique", "review", "save",
            "coherence_check", "arbitrate"} <= node_names


async def test_a_run_reaches_its_first_interruption(project):
    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project}"}}
    await graph.ainvoke(initial_state(str(project), "cdc", "cadrage", None,
                                       "Une plateforme de coaching à domicile."), config=config)
    snapshot = await graph.aget_state(config)
    assert snapshot.interrupts, "le graphe devrait s'arrêter pour poser ses questions"
    assert snapshot.interrupts[0].value["kind"] in {"questions", "review"}


async def test_a_full_run_writes_every_section_of_the_plan(project):
    """Le cœur de ce plan : les sections du plan « cdc » / « cadrage »
    rédigées de bout en bout, hors ligne, en reprenant à chaque interruption.

    Le brief attendait quinze sections ; le catalogue de la tâche 3 (déjà
    committé) réserve `cadre_reponse` au seul profil « consultation », donc
    le plan « cadrage » n'en compte que quatorze — vérifié directement contre
    `load_catalogue().cdc.sections` avant d'écrire ce test. Le nombre attendu
    est donc dérivé du catalogue plutôt que d'un compte figé en dur : si le
    catalogue change à nouveau, ce test le suivra au lieu de mentir.
    """
    from app.agent.templates import load_catalogue

    expected_sections = len(
        [s for s in load_catalogue().cdc.sections if "cadrage" in s.profils]
    )

    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project}"}}
    graph_input = initial_state(str(project), "cdc", "cadrage", None,
                           "Une plateforme de coaching sportif à domicile.")

    for _ in range(200):  # borne de sécurité : une boucle infinie doit échouer, pas pendre
        await graph.ainvoke(graph_input, config=config)
        snapshot = await graph.aget_state(config)
        if not snapshot.interrupts:
            break
        payload = snapshot.interrupts[0].value
        if payload["kind"] == "questions":
            graph_input = Command(resume={q["fact_id"]: "une réponse" for q in payload["questions"]})
        elif payload["kind"] == "review":
            graph_input = Command(resume={"action": "accept"})
        else:
            graph_input = Command(resume=[])
    else:
        pytest.fail("le run n'a pas convergé en 200 reprises")

    async with connection() as conn:
        sections = await load_sections(conn, project)
    assert len(sections) == expected_sections
    assert all(s["statut"] == "done" for s in sections)
    assert all(s["blocks"] for s in sections)


async def test_a_run_resumes_where_it_stopped(project):
    # Le point de reprise fait foi : un nouveau graphe compilé sur le même
    # thread retrouve l'état, sans rien réexécuter.
    config = {"configurable": {"thread_id": f"t-{project}"}}
    first = await compiled_graph()
    await first.ainvoke(initial_state(str(project), "cdc", "cadrage", None, "Une idée."),
                          config=config)
    before = (await first.aget_state(config)).values["cursor"]

    second = await compiled_graph()
    after = (await second.aget_state(config)).values["cursor"]
    assert after == before


async def test_purging_keeps_the_last_checkpoint(project):
    config = {"configurable": {"thread_id": f"t-{project}"}}
    graph = await compiled_graph()
    await graph.ainvoke(initial_state(str(project), "cdc", "cadrage", None, "Une idée."),
                         config=config)
    before = (await graph.aget_state(config)).values["cursor"]

    deleted = await purge_checkpoints(f"t-{project}")
    assert deleted > 0

    # Ce que la purge doit préserver : la capacité à reprendre.
    after = (await graph.aget_state(config)).values["cursor"]
    assert after == before
