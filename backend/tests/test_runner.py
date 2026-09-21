import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from app.agent.graph import initial_state
from app.core.db import connection
from app.projects.repository import create_project, project_for_user, set_run_status
from app.runs.events import subscribe
from app.runs.runner import RunAlreadyRunning, advance, start_run


@pytest_asyncio.fixture
async def project(migrated_db, monkeypatch):
    # Le graphe ne reçoit pas de transport : la passerelle lit le réglage.
    # Même montage que `tests/test_graph.py::project`, sans quoi le run
    # tenterait de vrais appels réseau au milieu de la suite hors-`network`.
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config
    config.settings.cache_clear()
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) "
                "values (%s, 'x', true) returning id",
                (f"runner-{uuid4()}@exemple.fr",),
            )
            user_id = (await cur.fetchone())[0]
        # Le fil est tiré AVANT l'insertion et réutilisé tel quel : le rendre
        # différent de celui écrit en base donnerait des tests qui passent
        # tout en pilotant un autre point de reprise que le projet.
        thread_id = f"thread-{uuid4()}"
        project_id = await create_project(
            conn, user_id, nom="CoachDom", documents="cdc",
            profil_cdc="consultation", profil_bp=None,
            thread_id=thread_id, templates_version="0.1",
        )
    yield {"project_id": project_id, "user_id": user_id,
           "thread_id": thread_id}
    from app.agent.checkpointer import close_checkpointer

    await close_checkpointer()
    config.settings.cache_clear()


async def _status(project_id, user_id):
    async with connection() as conn:
        row = await project_for_user(conn, project_id, user_id)
    return row["run_status"]


async def test_a_run_stops_on_its_first_interruption_and_says_so(project):
    graph_input = initial_state(str(project["project_id"]), "cdc",
                                "consultation", None, "Une idée.")
    await advance(str(project["project_id"]), project["thread_id"], graph_input)
    assert await _status(project["project_id"], project["user_id"]) == "waiting"


async def test_the_interruption_is_published(project):
    graph_input = initial_state(str(project["project_id"]), "cdc",
                                "consultation", None, "Une idée.")
    async with subscribe(str(project["project_id"])) as events:
        await advance(str(project["project_id"]), project["thread_id"], graph_input)
        received = []
        try:
            while True:
                received.append(await asyncio.wait_for(anext(events), timeout=0.2))
        except asyncio.TimeoutError:
            pass
    interactions = [e for e in received if e.name == "interaction"]
    assert interactions, "l'interruption n'a pas été publiée"
    assert "id" in interactions[-1].data, (
        "sans project_id d'interaction, /answer ne peut pas être idempotent"
    )
    assert interactions[-1].data["kind"] in {"questions", "review",
                                             "inconsistencies"}


async def test_a_failing_run_is_marked_failed_and_publishes_an_error(project):
    async with subscribe(str(project["project_id"])) as events:
        # Une entrée invalide : le catalogue refuse un profil inconnu, donc
        # `initial_state` lève dès la construction du plan. On appelle
        # `advance` avec un état déjà construit mais au plan vide, ce qui
        # fait sortir le graphe des bornes de son curseur.
        await advance(str(project["project_id"]), project["thread_id"],
                      {"plan": [], "cursor": 5})
        received = []
        try:
            while True:
                received.append(await asyncio.wait_for(anext(events), timeout=0.2))
        except asyncio.TimeoutError:
            pass
    assert await _status(project["project_id"], project["user_id"]) == "failed"
    errors = [e for e in received if e.name == "error"]
    assert errors, "un run en échec doit le dire sur le flux"
    assert errors[-1].data["reprenable"] is True


async def test_a_finished_run_purges_its_checkpoints(project):
    """`purge_checkpoints` est écrit et testé depuis le plan 3 et n'avait
    aucun appelant — constat 8 de la revue finale. Il en a un ici."""
    from app.agent import checkpointer

    calls = []

    async def _count_calls(thread_id, keep=1):
        calls.append((thread_id, keep))
        return 0

    real_purge = checkpointer.purge_checkpoints
    checkpointer.purge_checkpoints = _count_calls
    try:
        await advance(str(project["project_id"]), project["thread_id"],
                      None, _force_done=True)
    finally:
        checkpointer.purge_checkpoints = real_purge

    assert calls, "un run terminé doit purger ses points de reprise"
    assert calls[0][0] == project["thread_id"]
    assert await _status(project["project_id"], project["user_id"]) == "done"


async def test_two_starts_for_the_same_project_are_refused(project):
    graph_input = initial_state(str(project["project_id"]), "cdc",
                                "consultation", None, "Une idée.")
    start_run(str(project["project_id"]), project["thread_id"], graph_input)
    try:
        with pytest.raises(RunAlreadyRunning):
            start_run(str(project["project_id"]), project["thread_id"],
                      graph_input)
    finally:
        from app.runs.registry import cancel_all

        await cancel_all()
