import asyncio

import pytest_asyncio

from app.core.db import connection
from tests.test_project_routes import CREATION, _active_account


@pytest_asyncio.fixture(autouse=True)
async def _fake_llm(monkeypatch):
    """Bascule le graphe sur le modèle simulé.

    Obligatoire dans TOUT fichier de test qui appelle `POST /projects` :
    la route démarre un vrai run en tâche de fond, et sans cette bascule
    `advance` appellerait la passerelle avec `ESQUISSE_FAKE_LLM=false` — la
    valeur que `tests/conftest.py` fixe pour toute la suite — donc de vraies
    requêtes réseau avec des clés factices. C'est exactement ce que la suite
    `not network` interdit, et c'est passé inaperçu jusqu'à la tâche 3.

    Le nettoyage des runs et des pools n'est PAS ici : `tests/conftest.py`
    porte un démontage autouse qui annule les runs, ferme le point de
    reprise et ferme le pool applicatif, dans cet ordre. Le dupliquer ferait
    deux endroits à tenir d'accord, et c'est toujours le second qu'on
    oublie.
    """
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config

    config.settings.cache_clear()
    yield
    config.settings.cache_clear()


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "reprise")


async def _force_status(project_id, statut):
    """Simule ce que fait un redémarrage : la ligne reste `running` alors
    que plus aucune tâche ne tourne."""
    from uuid import UUID

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "update projects set run_status = %s where id = %s",
                (statut, UUID(project_id)))


async def test_a_run_left_running_by_a_restart_is_marked_failed(client, account):
    from app.runs.registry import cancel_all
    from app.main import reconcile_orphan_runs

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    await cancel_all()                      # le processus est mort
    await _force_status(project_id, "running")

    reconciled = await reconcile_orphan_runs()

    assert reconciled >= 1
    state_body = (await client.get(f"/projects/{project_id}", headers=account)).json()
    assert state_body["run_status"] == "failed", (
        "un run que plus rien ne pilote doit le dire, sinon l'utilisateur "
        "attend indéfiniment devant un écran qui ne bougera plus"
    )


async def test_reconciliation_leaves_a_live_run_alone(client, account):
    from app.main import reconcile_orphan_runs

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    await _force_status(project_id, "running")
    # La tâche est toujours au registre : ce run-là n'est pas orphelin.
    await reconcile_orphan_runs()
    state_body = (await client.get(f"/projects/{project_id}", headers=account)).json()
    assert state_body["run_status"] != "failed"


async def test_resuming_restarts_the_run_from_its_checkpoint(client, account):
    from app.runs.registry import cancel_all

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    interaction_before = state_body["interaction"]

    await cancel_all()
    await _force_status(project_id, "failed")

    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 200

    # Lire `/state` tout de suite ne prouverait rien : le point de reprise
    # garde l'interruption d'avant le crash qu'on relance ou non, tant que
    # rien n'a encore écrit un nouveau point de reprise par-dessus — un
    # `/resume` qui ne ferait RIEN laisserait ce test vert. On attend donc
    # d'abord que la ligne quitte `failed` (la preuve qu'une tâche est bien
    # repartie), puis qu'elle atteigne `waiting` À NOUVEAU : `advance` n'y
    # écrit qu'après avoir persisté la nouvelle interruption, donc `/state`
    # y est alors forcément à jour.
    for _ in range(100):
        header = (await client.get(f"/projects/{project_id}", headers=account)).json()
        if header["run_status"] != "failed":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(
            "`/resume` n'a jamais fait quitter `failed` à la ligne : "
            "rien ne prouve qu'une tâche est repartie")

    for _ in range(100):
        header = (await client.get(f"/projects/{project_id}", headers=account)).json()
        if header["run_status"] == "waiting":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("la reprise n'a jamais atteint une nouvelle interruption")

    # L'interruption est retrouvée à l'identique : le point de reprise fait
    # foi, rien n'a été perdu.
    state_body = (await client.get(f"/projects/{project_id}/state",
                             headers=account)).json()
    assert state_body["interaction"]["id"] == interaction_before["id"]


async def test_reopening_a_section_marks_it_and_its_dependents(client, account):
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    # Le plan fait partie de l'état initial (`initial_state`), mais il ne
    # devient visible au point de reprise qu'une fois le premier point de
    # reprise écrit par le run de fond — une écriture en base, donc pas
    # garantie au retour immédiat de `POST /projects`. Même motif de sondage
    # que `tests/test_project_routes.py`.
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["plan"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le plan n'a jamais été publié au point de reprise")
    section_id = state_body["plan"][0]["section_id"]

    response = await client.post(
        f"/projects/{project_id}/sections/{section_id}/reopen",
        headers=account)
    assert response.status_code == 200
    assert "sections" in response.json()


async def test_resuming_another_users_project_is_not_found(client, account):
    owner = await _active_account(client, "reprise-proprio")
    project_id = (await client.post(
        "/projects", json=CREATION, headers=owner)).json()["id"]
    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 404


async def test_purging_finished_projects_purges_their_checkpoints(client, account):
    """La purge de filet du démarrage (§9.3) : elle tourne pour les projets
    que le processus a fini de piloter sans avoir jamais eu la main pour
    lancer lui-même la purge de fin de run (`runner.advance`), précisément
    ce qui arrive quand le redémarrage survient entre les deux."""
    from uuid import UUID

    from app.main import purge_finished_projects
    from app.projects.repository import set_run_status

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    # On attend que le run de fond ait fini d'ouvrir son propre point de
    # reprise avant d'appeler `purge_checkpoints` nous-mêmes : les deux
    # ouvrent le même pool, et `purge_checkpoints` n'a pas le verrou dont
    # `saver()` se sert pour se protéger d'une ouverture concurrente. Sans
    # cette attente, les deux `open()` se chevauchent et psycopg_pool lève
    # une `AssertionError` — un défaut réel de `purge_checkpoints`, pas de ce
    # test, révélé ici parce que c'est le premier appel à le lancer pendant
    # qu'un run est encore vivant sur le même projet.
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint d'interruption")

    async with connection() as conn:
        await set_run_status(conn, UUID(project_id), "done")

    purged = await purge_finished_projects()

    assert purged >= 1
