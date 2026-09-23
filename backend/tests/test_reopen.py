import asyncio
from uuid import UUID

import pytest_asyncio

from app.agent import nodes
from app.agent.templates import load_catalogue
from app.core.db import connection
from app.projects import routes
from app.runs import registry
from tests.test_project_routes import CREATION, _active_account


@pytest_asyncio.fixture(autouse=True)
async def _fake_llm(monkeypatch):
    """Obligatoire dans tout fichier qui appelle `POST /projects` : voir
    `tests/test_resume.py::_fake_llm`."""
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config

    config.settings.cache_clear()
    yield
    config.settings.cache_clear()


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "reouverture")


async def _run_to_the_end(client, project_id, headers) -> dict:
    """Répond à chaque interaction comme un utilisateur pressé, par l'API,
    jusqu'à `done`. `done` ne suffit pas seul : juste après une réouverture,
    la ligne dit encore `done` alors que le registre pilote déjà le run."""
    for _ in range(4000):
        body = (await client.get(f"/projects/{project_id}/state", headers=headers)).json()
        status = body["projet"]["run_status"]
        interaction = body["interaction"]
        if status == "done" and not registry.is_running(project_id):
            return body
        assert status != "failed", body
        if status == "waiting" and interaction:
            if interaction["kind"] == "questions":
                reponse = {q["fact_id"]: "une réponse" for q in interaction["questions"]}
            elif interaction["kind"] == "review":
                reponse = {"action": "accept"}
            else:
                reponse = []
            await client.post(f"/projects/{project_id}/answer", headers=headers,
                              json={"interaction_id": interaction["id"], "reponse": reponse})
            continue
        await asyncio.sleep(0.02)
    raise AssertionError("le run n'est jamais arrivé au bout")


async def _finished_project(client, headers) -> tuple[str, dict]:
    project_id = (await client.post("/projects", json=CREATION, headers=headers)).json()["id"]
    return project_id, await _run_to_the_end(client, project_id, headers)


async def _mark_every_section(project_id) -> None:
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("update sections set note = -1 where project_id = %s",
                              (UUID(project_id),))


async def _statuses(project_id) -> dict[str, tuple[str, int | None]]:
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select document, section_id, statut, note from sections where project_id = %s",
                (UUID(project_id),))
            return {f"{d}.{s}": (statut, note) for d, s, statut, note in await cur.fetchall()}


def _spy_on_writing(monkeypatch) -> list[list[str]]:
    seen: list[list[str]] = []
    original = nodes.prompts.writing_prompt

    def spy(*args):
        seen.append(list(args[5]))
        return original(*args)

    monkeypatch.setattr(nodes.prompts, "writing_prompt", spy)
    return seen


def _expected_queue(state: dict, target: str) -> list[str]:
    closure = load_catalogue().sections_depending_on(target)
    return [f"{r['document']}.{r['section_id']}" for r in state["plan"]
            if f"{r['document']}.{r['section_id']}" in closure]


async def test_reopening_a_finished_project_rewrites_the_section_and_its_dependents(
        client, account, monkeypatch):
    project_id, state = await _finished_project(client, account)
    first = state["plan"][0]
    target = f"{first['document']}.{first['section_id']}"
    expected = _expected_queue(state, target)
    await _mark_every_section(project_id)
    written = _spy_on_writing(monkeypatch)

    response = await client.post(
        f"/projects/{project_id}/sections/{first['section_id']}/reopen",
        headers=account, json={"consigne": "Parler aussi des coachs"})

    assert response.status_code == 200
    assert response.json() == {"sections": expected, "touchees": len(expected),
                               "run_status": "running"}
    await _run_to_the_end(client, project_id, account)
    rewritten = {q for q, (_, note) in (await _statuses(project_id)).items() if note != -1}
    assert rewritten == set(expected)
    assert any("Parler aussi des coachs" in p for problems in written for p in problems)
    header = (await client.get(f"/projects/{project_id}", headers=account)).json()
    assert header["sections_faites"] == header["sections_total"] == len(state["plan"])


async def test_reopening_writes_running_immediately_so_the_screen_does_not_stall(
        client, account, monkeypatch):
    """`POST /reopen` rend `run_status: running` dans sa réponse, mais c'est
    la tâche de fond, `advance`, qui l'écrit en base — et seulement après son
    premier `await`. Si `GET /projects/{id}` relu tout de suite après rend
    encore `done`, l'écran de rédaction s'y arrête : il n'ouvre aucun flux et
    ne se rafraîchit jamais (constat 4 de la revue finale).

    Sans le retard posé ci-dessous, ce test passerait même sans le correctif
    : l'ordonnanceur donne presque toujours la main à la tâche de fond avant
    que la réponse HTTP ne soit sérialisée. Le retard force la fenêtre que le
    constat décrit — le graphe qui n'a pas encore consommé l'interruption —
    et rend le test probant plutôt que chanceux."""
    from app.runs import runner

    project_id, state = await _finished_project(client, account)

    original_advance = runner.advance

    async def slow_advance(*args, **kwargs):
        await asyncio.sleep(0.2)
        return await original_advance(*args, **kwargs)

    monkeypatch.setattr(runner, "advance", slow_advance)

    response = await client.post(
        f"/projects/{project_id}/sections/{state['plan'][0]['section_id']}/reopen",
        headers=account)
    assert response.status_code == 200

    header = (await client.get(f"/projects/{project_id}", headers=account)).json()
    assert header["run_status"] == "running"

    await _run_to_the_end(client, project_id, account)


async def test_reopening_without_a_body_gives_the_writer_a_reason(client, account, monkeypatch):
    project_id, state = await _finished_project(client, account)
    written = _spy_on_writing(monkeypatch)

    response = await client.post(
        f"/projects/{project_id}/sections/{state['plan'][0]['section_id']}/reopen",
        headers=account)

    assert response.status_code == 200
    await _run_to_the_end(client, project_id, account)
    assert any(nodes.REOPENED_WITHOUT_NOTE in problems for problems in written)


async def test_reopening_while_the_run_waits_is_refused_and_marks_nothing(client, account):
    """Le run de fond est arrêté à sa première interruption et n'écrit rien
    pendant ce temps : on peut donc poser des lignes `sections` à la main
    sans qu'il ne vienne s'en mêler — même motif que
    `tests/test_resume.py::test_reopening_counts_the_rows_it_actually_marked`.

    Sans ces lignes, la table `sections` est encore vide au moment du refus,
    et `all(statut != "reopened" ...)` est vraie pour n'importe quelle
    raison : elle ne distingue pas un refus qui ne marque rien d'un refus qui
    marquerait AVANT de répondre 409. Ces lignes rendent l'assertion
    discriminante.
    """
    from app.agent.projections import save_section
    from app.agent.state import Paragraph, SectionRef

    project_id = (await client.post("/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(200):
        state = (await client.get(f"/projects/{project_id}/state", headers=account)).json()
        if state["projet"]["run_status"] == "waiting" and state["plan"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint sa première interruption")

    first = state["plan"][0]
    target = f"{first['document']}.{first['section_id']}"
    expected = _expected_queue(state, target)
    async with connection() as conn:
        for order, qualified in enumerate(expected, start=1):
            document, _, bare = qualified.partition(".")
            await save_section(
                conn, UUID(project_id),
                SectionRef(document=document, section_id=bare, order=order),
                blocks=[Paragraph(text="x")], statut="done", note=8, revisions=1)

    response = await client.post(
        f"/projects/{project_id}/sections/{first['section_id']}/reopen",
        headers=account)

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "reouverture_impossible"}}
    assert all(statut != "reopened" for statut, _ in (await _statuses(project_id)).values())


async def test_reopening_during_an_export_is_refused_and_marks_nothing(
        client, account, monkeypatch):
    project_id, state = await _finished_project(client, account)
    monkeypatch.setattr(routes, "is_exporting", lambda pid: True)

    response = await client.post(
        f"/projects/{project_id}/sections/{state['plan'][0]['section_id']}/reopen",
        headers=account)

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "export_deja_en_cours"}}
    assert not registry.is_running(project_id)
    assert all(statut == "done" for statut, _ in (await _statuses(project_id)).values())


async def test_a_second_reopen_racing_the_first_says_the_rewrite_already_left(
        client, account, monkeypatch):
    """Deux clics sur « Rouvrir » : le second doit dire que la réécriture est
    déjà partie, pas que la rédaction doit être terminée — ce qui serait faux
    puisqu'elle vient de l'être. On force la course : juste avant l'appel à
    `start_run`, un faux run est déjà enregistré dans le registre, comme si
    une première requête l'avait fait entre le contrôle initial et cet appel.
    """
    project_id, state = await _finished_project(client, account)
    original_set_run_status = routes.set_run_status

    async def _racing_set_run_status(conn, pid, status):
        await original_set_run_status(conn, pid, status)
        # Simule le second clic : un run est déjà en registre quand
        # `reopen` appelle `start_run` juste après.
        registry.register(str(pid), asyncio.create_task(asyncio.sleep(10)))

    monkeypatch.setattr(routes, "set_run_status", _racing_set_run_status)

    try:
        response = await client.post(
            f"/projects/{project_id}/sections/{state['plan'][0]['section_id']}/reopen",
            headers=account)

        assert response.status_code == 409
        assert response.json() == {"detail": {"code": "reecriture_deja_lancee"}}
    finally:
        await registry.cancel_all()
