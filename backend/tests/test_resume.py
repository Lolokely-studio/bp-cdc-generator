import asyncio

import pytest_asyncio

from app.core.db import connection
from tests.test_project_routes import CREATION, MOT_DE_PASSE, _active_account


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


async def _stillborn_project(client, label, *, idee="Une idée jamais lancée."):
    """Un projet dont le fil n'a JAMAIS tourné : aucun point de reprise
    n'existe pour lui, par construction plutôt que par minutage.

    Contrairement aux autres comptes de ce fichier, on n'appelle pas
    `POST /projects` : la route démarre un vrai run en tâche de fond, et
    rien ne garantit qu'il n'a pas déjà écrit son premier point de reprise
    avant qu'on ne le tue — un test qui dépendrait de ce minutage passerait
    ou non selon la machine. On écrit la ligne directement, sans jamais
    appeler `start_run`, ce qui rend l'absence de point de reprise certaine
    et non probable.
    """
    from uuid import uuid4

    from app.projects.repository import create_project

    email = f"{label}-{uuid4()}@exemple.fr"
    await client.post("/auth/register",
                      json={"email": email, "mot_de_passe": MOT_DE_PASSE})
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "update users set is_active = true where email = %s", (email,))
            await cur.execute("select id from users where email = %s", (email,))
            user_id = (await cur.fetchone())[0]
        project_id = await create_project(
            conn, user_id, nom="Mort-né", documents="cdc",
            profil_cdc="consultation", profil_bp=None,
            thread_id=f"thread-{uuid4()}", templates_version="0.1",
            idee=idee,
        )
    response = await client.post(
        "/auth/login", json={"email": email, "mot_de_passe": MOT_DE_PASSE})
    headers = {"Authorization": f"Bearer {response.json()['jeton']}"}
    return str(project_id), headers


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


async def test_resuming_a_run_still_registered_is_a_noop(client, account):
    """Le garde `registry.is_running` de `/resume` : rien ne l'exerçait, et
    le retirer laissait les cinq autres tests de ce fichier verts. Sans lui,
    `/resume` relancerait un fil déjà piloté par une tâche vivante — deux
    tâches asyncio avançant le même point de reprise, la corruption exacte
    que `app/runs/registry.py` existe pour empêcher.

    On force l'entrée du registre avec une tâche factice plutôt que de
    compter sur le timing du vrai run de fond : le vrai run peut avoir déjà
    atteint son interruption (et donc quitté le registre) avant que ce test
    n'ait la main, ce qui rendrait un sondage sur le vrai run non fiable.
    """
    from app.runs import registry

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]

    async def _still_running():
        await asyncio.sleep(30)

    # Remplace l'entrée du registre, quel que soit son état : `register`
    # ne retire que la tâche dont il connaît l'IDENTITÉ (voir sa docstring),
    # donc la vraie tâche de création, si elle se termine ensuite, ne pourra
    # pas effacer celle-ci par erreur.
    registry.register(project_id, asyncio.create_task(_still_running()))
    assert registry.is_running(project_id)

    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 200
    assert response.json() == {"reprise": False, "run_status": "running"}


async def test_resuming_rewrites_facts_before_relaunching(client, account, monkeypatch):
    """`/resume` doit réécrire les faits depuis le point de reprise AVANT de
    relancer (§4.6) : rien ne le vérifiait, et retirer l'appel à `save_facts`
    laissait les cinq autres tests de ce fichier verts."""
    from app.projects import routes
    from app.runs.registry import cancel_all

    captured = []
    real_save_facts = routes.save_facts

    async def _spy(conn, project_id, facts):
        captured.append(facts)
        return await real_save_facts(conn, project_id, facts)

    monkeypatch.setattr(routes, "save_facts", _spy)

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint d'interruption")

    await cancel_all()
    await _force_status(project_id, "failed")

    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 200
    assert captured, "`save_facts` n'a pas été appelée par `/resume`"


async def test_reopening_calls_mark_for_reopening_with_the_transitive_closure(
        client, account, monkeypatch):
    """`mark_for_reopening` trouve enfin un appelant (constat de la revue du
    plan 3) : rien ne vérifiait qu'il est bien appelé, ni avec quoi. Retirer
    l'appel — ou lui passer autre chose que la fermeture transitive de
    `sections_depending_on` — laissait `..._marks_it_and_its_dependents`
    vert, puisque cette route-là ne vérifie que la forme de la réponse."""
    from app.agent.templates import load_catalogue
    from app.projects import routes

    captured = []
    real_mark = routes.mark_for_reopening

    async def _spy(conn, project_id, qualified_ids):
        captured.append(qualified_ids)
        return await real_mark(conn, project_id, qualified_ids)

    monkeypatch.setattr(routes, "mark_for_reopening", _spy)

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["plan"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le plan n'a jamais été publié au point de reprise")
    section_id = state_body["plan"][0]["section_id"]

    await client.post(f"/projects/{project_id}/sections/{section_id}/reopen",
                      headers=account)

    assert captured, "`mark_for_reopening` n'a pas été appelée par `/reopen`"
    assert captured[-1] == load_catalogue().sections_depending_on(f"cdc.{section_id}")


# --- Étape 9 : `/resume` ne reprend que ce qui est à reprendre -------------


async def test_resuming_a_waiting_project_starts_nothing(client, account):
    """`waiting` n'est pas un crash : c'est une interruption bien vivante.
    Relancer rejouerait le nœud interrompu et ferait refuser par le 409 de
    `/answer` la vraie réponse que l'utilisateur est peut-être en train
    d'envoyer."""
    from app.runs.registry import cancel_all

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint d'interruption")
    interaction_before = state_body["interaction"]

    # Neutralise le registre, comme les autres tests de ce fichier : le
    # point est de tester la garde sur `run_status`, pas de dépendre du
    # minutage exact auquel la tâche de fond quitte le registre.
    await cancel_all()
    await _force_status(project_id, "waiting")

    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 200
    assert response.json() == {"reprise": False, "run_status": "waiting"}

    state_body = (await client.get(f"/projects/{project_id}/state",
                             headers=account)).json()
    assert state_body["interaction"]["id"] == interaction_before["id"], (
        "`/resume` a rejoué l'interruption alors que rien n'avait crashé"
    )


async def test_resuming_a_done_project_starts_nothing(client, account):
    from app.runs.registry import cancel_all

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    await cancel_all()
    await _force_status(project_id, "done")

    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 200
    assert response.json() == {"reprise": False, "run_status": "done"}


async def test_resuming_an_idle_project_with_a_checkpoint_starts_nothing(client, account):
    """`idle` avec un point de reprise DÉJÀ écrit n'est pas mort-né : c'est
    une écriture de statut en retard sur un run par ailleurs vivant à son
    premier tour. `/resume` continue de le refuser — seul un `idle` SANS
    point de reprise devient reprenable (constat 1 de la revue finale)."""
    from app.runs.registry import cancel_all

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint d'interruption")

    await cancel_all()
    await _force_status(project_id, "idle")

    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 200
    assert response.json() == {"reprise": False, "run_status": "idle"}


async def test_resuming_a_stillborn_idle_project_starts_it(client, migrated_db):
    """Constat 1 de la revue finale : un processus tué entre l'insertion de
    la ligne et le démarrage de la tâche la laisse `idle` sans le moindre
    point de reprise — pour toujours, avant ce correctif. `/resume` doit
    reconstruire `initial_state` depuis la ligne et repartir."""
    project_id, headers = await _stillborn_project(client, "mort-ne-idle")

    response = await client.post(f"/projects/{project_id}/resume", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"reprise": True, "run_status": "running"}

    for _ in range(100):
        header = (await client.get(f"/projects/{project_id}", headers=headers)).json()
        if header["run_status"] == "waiting":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(
            "le projet mort-né relancé n'a jamais atteint sa première interruption")


async def test_resuming_a_stillborn_project_without_an_idea_refuses(client, migrated_db):
    """Constat 1 de la revue finale : une ligne écrite avant la migration
    0004 n'a pas d'idée. La reconstruire depuis la ligne relancerait le
    graphe sur une idée vide — `/resume` refuse plutôt."""
    project_id, headers = await _stillborn_project(
        client, "mort-ne-sans-idee", idee=None)
    async with connection() as conn:
        async with conn.cursor() as cur:
            from uuid import UUID

            await cur.execute(
                "update projects set run_status = 'failed' where id = %s",
                (UUID(project_id),))

    response = await client.post(f"/projects/{project_id}/resume", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"reprise": False, "run_status": "failed"}


async def test_a_run_whose_first_advance_fails_can_be_resumed_to_waiting(
        client, account, monkeypatch):
    """Constat 1 de la revue finale, chemin complet : le premier `advance`
    échoue AVANT d'écrire le moindre point de reprise (un délai d'attente du
    pool du point de reprise, par exemple), la ligne passe `failed`. Avant
    le correctif, `/resume` rejouait `advance(..., None)`, LangGraph
    refusait, et la ligne retombait en `failed` en boucle."""
    from app.runs import runner

    real_compiled_graph = runner.compiled_graph
    should_fail = True

    async def _flaky_compiled_graph():
        nonlocal should_fail
        if should_fail:
            should_fail = False
            raise RuntimeError("délai d'attente simulé du pool du point de reprise")
        return await real_compiled_graph()

    monkeypatch.setattr(runner, "compiled_graph", _flaky_compiled_graph)

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]

    for _ in range(100):
        header = (await client.get(f"/projects/{project_id}", headers=account)).json()
        if header["run_status"] == "failed":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le premier `advance` n'a jamais échoué")

    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 200
    assert response.json() == {"reprise": True, "run_status": "running"}

    for _ in range(100):
        header = (await client.get(f"/projects/{project_id}", headers=account)).json()
        if header["run_status"] == "waiting":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(
            "le run mort-né relancé n'a jamais atteint d'interruption")


async def test_two_concurrent_resumes_never_return_500(client, account):
    """Constat 3 de la revue finale : deux `/resume` concurrents passent
    tous deux le garde `is_running`, attendent `aget_state` et `save_facts`,
    puis se disputent `start_run` — le second lève `RunAlreadyRunning`, qui
    doit être rattrapé plutôt que de rendre un 500."""
    from app.runs.registry import cancel_all

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint d'interruption")

    await cancel_all()
    await _force_status(project_id, "failed")

    results = await asyncio.gather(
        client.post(f"/projects/{project_id}/resume", headers=account),
        client.post(f"/projects/{project_id}/resume", headers=account),
    )
    statuses = [r.status_code for r in results]
    assert all(s == 200 for s in statuses), (
        f"un double clic sur « Reprendre » a rendu {statuses}"
    )
    bodies = [r.json() for r in results]
    assert {"reprise": True, "run_status": "running"} in bodies, (
        "aucune des deux requêtes concurrentes n'a relancé le run"
    )


async def test_resuming_an_orphaned_running_project_restarts_it(client, account):
    """Le second cas où `/resume` doit agir : `running` sans tâche vivante
    au registre — un redémarrage survenu avant que la réconciliation n'ait
    eu la main."""
    from app.runs.registry import cancel_all

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint d'interruption")
    interaction_before = state_body["interaction"]

    await cancel_all()
    # `running`, et non `failed` : l'autre statut sur lequel `/resume` doit
    # agir.
    await _force_status(project_id, "running")

    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 200
    assert response.json() == {"reprise": True, "run_status": "running"}

    for _ in range(100):
        header = (await client.get(f"/projects/{project_id}", headers=account)).json()
        if header["run_status"] == "waiting":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("la reprise n'a jamais atteint une nouvelle interruption")

    state_body = (await client.get(f"/projects/{project_id}/state",
                             headers=account)).json()
    assert state_body["interaction"]["id"] == interaction_before["id"]


async def test_resuming_passes_the_checkpoints_facts_to_save_facts(
        client, account, monkeypatch):
    """`/resume` doit transmettre à `save_facts` les faits du point de
    reprise, pas un dictionnaire vide : la seule assertion précédente était
    que `save_facts` ait été appelée, ce qu'un appel avec `{}` satisfaisait
    déjà."""
    from tests.test_answer import _answer_for, _wait_for_interaction
    from app.projects import routes
    from app.runs.registry import cancel_all

    captured = []
    real_save_facts = routes.save_facts

    async def _spy(conn, project_id, facts):
        captured.append(facts)
        return await real_save_facts(conn, project_id, facts)

    monkeypatch.setattr(routes, "save_facts", _spy)

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)
    await client.post(f"/projects/{project_id}/answer",
                      json={"interaction_id": interaction["id"],
                            "reponse": _answer_for(interaction)},
                      headers=account)

    # Un statut arrêté ET une interruption réellement nouvelle : même motif
    # que `test_answer.py::test_answering_advances_the_run` — une boucle qui
    # s'arrête sur `interaction: null`, l'état de passage entre deux
    # interruptions, capture un état transitoire et compare contre `None`.
    for _ in range(200):
        header = (await client.get(f"/projects/{project_id}", headers=account)).json()
        pending = (await client.get(f"/projects/{project_id}/state",
                                    headers=account)).json()["interaction"]
        if (header["run_status"] == "waiting" and pending is not None
                and pending["id"] != interaction["id"]):
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run ne s'est pas arrêté sur l'interruption suivante")

    await cancel_all()
    await _force_status(project_id, "failed")

    response = await client.post(f"/projects/{project_id}/resume",
                                headers=account)
    assert response.status_code == 200

    assert captured, "`save_facts` n'a pas été appelée par `/resume`"
    assert captured[-1] != {}, (
        "`/resume` a transmis un dictionnaire vide à `save_facts` au lieu "
        "des faits du point de reprise"
    )


# --- Étape 9 : la réconciliation n'écrase pas un statut plus récent --------


async def test_reconciliation_does_not_overwrite_a_status_more_recent_than_running(
        client, account, monkeypatch):
    """Deux lectures désynchronisées : la réconciliation lit
    `running_projects`, puis, avant d'écrire, le run atteint `waiting` de
    lui-même. Sans la garde `where run_status = 'running'`, l'écriture agit
    sur une photo périmée et écrase ce statut plus récent."""
    from uuid import UUID

    from app.main import reconcile_orphan_runs
    from app.projects import repository

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(100):
        header = (await client.get(f"/projects/{project_id}", headers=account)).json()
        if header["run_status"] == "waiting":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint `waiting`")
    # Laisse le rappel de fin de tâche du registre s'exécuter : `advance`
    # écrit `waiting` avant de rendre la main, le registre l'oublie au tour
    # de boucle suivant, pas au même instant.
    await asyncio.sleep(0.1)

    async def _stale_snapshot(conn):
        # La photo qu'aurait prise `running_projects` juste AVANT que le
        # statut ne devienne `waiting` : la ligne y figure encore.
        return [{"id": UUID(project_id), "thread_id": "peu importe"}]

    monkeypatch.setattr(repository, "running_projects", _stale_snapshot)

    reconciled = await reconcile_orphan_runs()

    assert reconciled == 0, (
        "la réconciliation a compté une ligne qu'elle n'a pas pu passer à "
        "`failed`, faux positif"
    )
    header = (await client.get(f"/projects/{project_id}", headers=account)).json()
    assert header["run_status"] == "waiting", (
        "la réconciliation a écrasé un statut plus récent que `running`"
    )


# --- Étape 9 : tests manquants ---------------------------------------------


async def test_purging_finished_projects_reduces_checkpoint_rows_and_leaves_others_alone(
        client, account):
    """La purge doit vraiment réduire le nombre de points de reprise d'un
    projet `done`, et ne pas toucher à celui d'un projet qui ne l'est pas —
    jusqu'ici, seul le COMPTE de projets purgés était vérifié."""
    from uuid import UUID

    from app.agent.checkpointer import checkpointer_pool
    from app.main import purge_finished_projects
    from app.projects.repository import set_run_status

    done_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    other_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]

    for pid in (done_id, other_id):
        for _ in range(100):
            state_body = (await client.get(f"/projects/{pid}/state",
                                     headers=account)).json()
            if state_body["interaction"] is not None:
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("le run n'a jamais atteint d'interruption")

    async def _thread_id(pid):
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "select thread_id from projects where id = %s", (UUID(pid),))
                return (await cur.fetchone())[0]

    async def _checkpoint_count(thread_id):
        pool = checkpointer_pool()
        await pool.open(wait=True)
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "select count(*) as n from checkpoints where thread_id = %s",
                (thread_id,))
            return (await cur.fetchone())["n"]

    done_thread = await _thread_id(done_id)
    other_thread = await _thread_id(other_id)

    before_done = await _checkpoint_count(done_thread)
    before_other = await _checkpoint_count(other_thread)
    assert before_done > 1, (
        "il faut plusieurs points de reprise pour que la purge ait un effet observable"
    )

    async with connection() as conn:
        await set_run_status(conn, UUID(done_id), "done")

    purged = await purge_finished_projects()
    assert purged >= 1

    after_done = await _checkpoint_count(done_thread)
    after_other = await _checkpoint_count(other_thread)

    assert after_done < before_done, "la purge n'a rien retiré du projet `done`"
    assert after_other == before_other, "la purge a touché un projet qui n'est pas `done`"


async def test_reopening_a_section_on_a_bp_project(client, account):
    payload = {"nom": "Budget", "documents": "bp", "profil_bp": "banque",
               "idee": "Une plateforme de coaching sportif à domicile."}
    project_id = (await client.post(
        "/projects", json=payload, headers=account)).json()["id"]
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
    assert all(q.startswith("bp.") for q in response.json()["sections"])


async def test_reopening_a_section_on_a_both_project(client, account):
    payload = {"nom": "Complet", "documents": "both",
               "profil_cdc": "consultation", "profil_bp": "banque",
               "idee": "Une plateforme de coaching sportif à domicile."}
    project_id = (await client.post(
        "/projects", json=payload, headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["plan"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le plan n'a jamais été publié au point de reprise")
    # Le CDC est posé entièrement avant le BP (`plan_for`) : le premier
    # élément du plan est donc un `cdc`.
    section_id = state_body["plan"][0]["section_id"]
    assert state_body["plan"][0]["document"] == "cdc"

    response = await client.post(
        f"/projects/{project_id}/sections/{section_id}/reopen",
        headers=account)
    assert response.status_code == 200
    assert all(q.startswith("cdc.") for q in response.json()["sections"])


async def test_reopening_an_unknown_section_is_not_found(client, account):
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]

    response = await client.post(
        f"/projects/{project_id}/sections/section-qui-n-existe-pas/reopen",
        headers=account)
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "section_introuvable"}}


async def test_reopening_response_matches_the_closure_and_the_touched_count(
        client, account):
    """Le contenu exact de la réponse, pas seulement la présence de la clé
    `sections` que le premier test de cette route vérifiait."""
    from app.agent.templates import load_catalogue

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["plan"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le plan n'a jamais été publié au point de reprise")
    section_id = state_body["plan"][0]["section_id"]
    expected = load_catalogue().sections_depending_on(f"cdc.{section_id}")

    response = await client.post(
        f"/projects/{project_id}/sections/{section_id}/reopen",
        headers=account)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"sections", "touchees"}
    assert body["sections"] == sorted(expected)
    # Un projet tout juste créé n'a encore aucune ligne `sections` :
    # `mark_for_reopening` ne peut rien y marquer.
    assert body["touchees"] == 0


async def test_reopening_counts_the_rows_it_actually_marked(client, account):
    """`touchees` figé à 0 laissait passer tous les tests.

    Un projet neuf n'a encore aucune ligne `sections`, donc 0 y est toujours
    la bonne réponse : le test voisin ne pouvait pas distinguer un compte
    juste d'un compte figé. On écrit d'abord les sections de la fermeture,
    puis on exige qu'elles soient toutes comptées. Le run de fond s'arrête à
    sa première interruption avant d'écrire la moindre section, donc rien ne
    vient se mêler à ces lignes.
    """
    from app.agent.projections import save_section
    from app.agent.state import Paragraph, SectionRef
    from app.agent.templates import load_catalogue

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                       headers=account)).json()
        if state_body["plan"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le plan n'a jamais été publié au point de reprise")
    section_id = state_body["plan"][0]["section_id"]
    expected = load_catalogue().sections_depending_on(f"cdc.{section_id}")
    assert len(expected) > 1, "la fermeture doit dépasser la section demandée"

    async with connection() as conn:
        for order, qualified in enumerate(sorted(expected), start=1):
            document, _, bare = qualified.partition(".")
            await save_section(
                conn, project_id,
                SectionRef(document=document, section_id=bare, order=order),
                blocks=[Paragraph(text="x")], statut="done", note=8,
                revisions=0)

    response = await client.post(
        f"/projects/{project_id}/sections/{section_id}/reopen",
        headers=account)
    assert response.json()["touchees"] == len(expected)
