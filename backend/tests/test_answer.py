import asyncio

import pytest_asyncio

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
    return await _active_account(client, "reponses")


async def _wait_for_interaction(client, project_id, headers):
    """L'interaction en attente, une fois que le run l'a atteinte.

    Le run tourne en tâche de fond : sans cette attente, le test lirait un
    état où rien n'est encore arrivé et passerait pour de mauvaises raisons.
    """
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=headers)).json()
        if state_body["interaction"] is not None:
            return state_body["interaction"]
        await asyncio.sleep(0.05)
    raise AssertionError("le run n'a jamais atteint d'interruption")


def _answer_for(interaction):
    """Une réponse plausible selon le type d'interruption."""
    if interaction["kind"] == "questions":
        return {q["fact_id"]: "une réponse" for q in interaction["questions"]}
    if interaction["kind"] == "review":
        return {"action": "accept"}
    return []


async def _wait_for_status(client, project_id, headers, expected):
    """Attend que l'entête annonce `expected`, et le rend.

    Le statut et le point de reprise ne deviennent pas visibles au même
    instant : le second l'est dès la fin d'`ainvoke`, le premier une
    écriture en base plus tard. Un test qui a vu l'interruption n'a donc
    aucune garantie sur le statut.
    """
    import asyncio

    for _ in range(100):
        header = (await client.get(f"/projects/{project_id}",
                                   headers=headers)).json()
        if header["run_status"] == expected:
            return header
        await asyncio.sleep(0.05)
    raise AssertionError(f"le statut n'a jamais atteint `{expected}`")


async def test_answering_advances_the_run(client, account):
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)

    response = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": interaction["id"],
              "reponse": _answer_for(interaction)},
        headers=account)
    assert response.status_code == 200

    # Le run repart : soit il atteint une autre interruption, soit il finit.
    for _ in range(200):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        current = state_body["interaction"]
        if current is None or current["id"] != interaction["id"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a pas dépassé l'interruption répondue")


async def test_answering_twice_does_not_advance_twice(client, account):
    """Le double-clic, et le §6.2.

    La seconde requête doit répondre 200 sans rien rejouer. Si elle rejouait,
    la réponse serait consommée par l'interruption SUIVANTE et tout le reste
    du run serait décalé d'un cran — en silence.

    Le second appel n'est envoyé qu'une fois le run passé à autre chose,
    et pas immédiatement après le premier. Un aller-retour immédiat serait
    absorbé par le registre (`RunAlreadyRunning`, tâche 3) parce que le
    premier run tourne encore : ce test passerait alors pour cette
    raison-là, pas parce que l'identifiant d'interruption est reconnu
    comme périmé — constaté par mutation : retirer la comparaison
    d'identifiant dans la route ne faisait tomber que
    `..._stale_interaction_id_changes_nothing`, celui-ci restait vert pour
    la mauvaise raison.
    """
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)
    body = {"interaction_id": interaction["id"],
             "reponse": _answer_for(interaction)}

    first = await client.post(f"/projects/{project_id}/answer",
                                 json=body, headers=account)
    assert first.status_code == 200

    for _ in range(200):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        current = state_body["interaction"]
        if current is None or current["id"] != interaction["id"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a pas dépassé l'interruption répondue")

    second = await client.post(f"/projects/{project_id}/answer",
                                json=body, headers=account)

    assert second.status_code == 200, (
        "une réponse déjà consommée doit renvoyer l'état courant, pas une "
        "erreur : le front ne peut pas distinguer un double-clic d'un échec"
    )
    assert second.json()["rejoue"] is False
    # Le drapeau ne suffit pas : une route qui reprend quand même tout en
    # répondant `rejoue: False` le laissait au vert. On regarde donc le
    # graphe, pas la réponse.
    #
    # L'attente n'est pas du confort, ici non plus : `start_run` rend la
    # main avant que la tâche de fond ait avancé (même mécanique que
    # `test_a_stale_interaction_id_changes_nothing`). Sans elle, la lecture
    # de `/state` gagne une course contre la reprise fautive au lieu de la
    # débusquer — constaté par mutation : la branche « périmé » reprenant
    # quand même laissait ce test vert à tous les coups tant que cette
    # attente manquait.
    await asyncio.sleep(1)
    after = (await client.get(f"/projects/{project_id}/state",
                              headers=account)).json()["interaction"]
    assert after is None or after["id"] == current["id"], (
        "le second appel a fait avancer le graphe"
    )


async def test_a_stale_interaction_id_changes_nothing(client, account):
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)

    response = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": "une-interruption-qui-n-existe-pas",
              "reponse": {}},
        headers=account)
    assert response.status_code == 200
    assert response.json()["rejoue"] is False

    # L'attente n'est pas du confort. Sans elle, la tâche de fond n'a pas
    # bougé quand on lit, et l'assertion gagne une course au lieu de
    # vérifier quelque chose : avec l'attente elle passe sur le code livré
    # et TOMBE sur une route qui reprendrait malgré l'identifiant périmé.
    await asyncio.sleep(1)

    state_body = (await client.get(f"/projects/{project_id}/state",
                             headers=account)).json()
    assert state_body["interaction"]["id"] == interaction["id"], (
        "un identifiant périmé a fait avancer le graphe"
    )


async def test_answering_another_users_project_is_not_found(client, account):
    owner = await _active_account(client, "autre-proprio")
    project_id = (await client.post(
        "/projects", json=CREATION, headers=owner)).json()["id"]

    response = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": "peu-importe", "reponse": {}},
        headers=account)
    assert response.status_code == 404


async def test_a_malformed_answer_is_refused_and_consumes_nothing(client, account):
    """Le constat le plus grave du plan, réduit à un test.

    Une liste au lieu d'une correspondance tuait le run, et le point de
    reprise gardant la valeur, une reprise correcte replantait à
    l'identique : le projet ne revenait plus jamais.
    """
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)

    refused = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": interaction["id"], "reponse": ["a", "b"]},
        headers=account)
    assert refused.status_code == 422

    # Rien n'a été consommé : la même interruption attend toujours, et une
    # réponse correcte passe.
    state_body = (await client.get(f"/projects/{project_id}/state",
                                   headers=account)).json()
    assert state_body["interaction"]["id"] == interaction["id"]
    accepted = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": interaction["id"],
              "reponse": _answer_for(interaction)},
        headers=account)
    assert accepted.status_code == 200
    assert accepted.json()["rejoue"] is True


async def test_a_null_answer_does_not_kill_the_node(client, account):
    """Le garde de `ask_questions` n'est pas redondant avec le 422 de la
    route : il défend une porte que la route laisse volontairement ouverte.

    `_EXPECTED_ANSWER` de la route ne s'applique QUE si `reponse` n'est pas
    `None` — `AnswerRequest.reponse` vaut `Any = None`, et une réponse
    explicitement nulle n'est pas une malformation qu'on veut refuser au
    seuil. Elle atteint donc le nœud tel quelle. Retirer le garde du nœud ne
    fait tomber AUCUN test si l'on ne teste que le cas de la liste — la
    route bloque déjà les listes avant que le nœud ne les voie — d'où ce
    test séparé, constaté par mutation : sans lui, le garde de `ask_questions`
    pouvait disparaître sans que rien ne le remarque.
    """
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)
    assert interaction["kind"] == "questions"

    response = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": interaction["id"], "reponse": None},
        headers=account)
    assert response.status_code == 200

    await asyncio.sleep(1)
    state_body = (await client.get(f"/projects/{project_id}/state",
                                   headers=account)).json()
    assert state_body["projet"]["run_status"] != "failed", (
        "une réponse nulle a tué le run : le garde du nœud a manqué"
    )


async def test_the_answer_reaches_the_graph_unchanged(client, account, monkeypatch):
    """Rien ne vérifiait que la réponse de l'utilisateur arrive au graphe.

    Reprendre avec une charge vide laissait les quatre tests verts. On
    intercepte donc le `Command` remis au pilote — les faits répondus ne
    sont projetés qu'au nœud `save`, bien plus tard, donc `/state` ne peut
    pas servir de témoin ici.
    """
    from app.projects import routes

    captured = []
    real_start_run = routes.start_run

    def _spying_start_run(pid, tid, gi):
        # On espionne, on ne remplace pas : un simple `captured.append` sans
        # relais vers `real_start_run` empêchait le run de départ d'avancer
        # (la création de projet appelle aussi `start_run`), donc
        # `_wait_for_interaction` n'atteignait jamais d'interruption et le
        # test échouait avant même d'exercer ce qu'il veut vérifier.
        captured.append(gi)
        return real_start_run(pid, tid, gi)

    monkeypatch.setattr(routes, "start_run", _spying_start_run)

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)
    payload = _answer_for(interaction)
    await client.post(f"/projects/{project_id}/answer",
                      json={"interaction_id": interaction["id"],
                            "reponse": payload},
                      headers=account)

    assert captured, "le pilote n'a pas été appelé"
    assert captured[-1].resume == {interaction["id"]: payload}


async def test_a_race_on_the_same_answer_is_absorbed(client, account, monkeypatch):
    """La seule branche écrite pour une vraie course, et rien ne l'exerçait.

    Supprimer son `except` laissait les 414 tests verts, alors qu'un vrai
    double-clic simultané rend alors un 500.
    """
    from app.projects import routes
    from app.runs.runner import RunAlreadyRunning

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)

    def _already(project_id, thread_id, graph_input):
        raise RunAlreadyRunning(project_id)

    monkeypatch.setattr(routes, "start_run", _already)
    response = await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": interaction["id"],
              "reponse": _answer_for(interaction)},
        headers=account)

    assert response.status_code == 200
    assert response.json() == {"rejoue": False, "run_status": "running"}


async def test_every_answer_reports_the_run_status(client, account):
    """La moitié du contrat de réponse n'était assertée nulle part : retirer
    `run_status` des trois retours laissait la suite verte."""
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    interaction = await _wait_for_interaction(client, project_id, account)
    # `_wait_for_interaction` sonde `/state`, qui lit le point de reprise —
    # et celui-ci devient visible À L'INTÉRIEUR d'`ainvoke`, donc AVANT que
    # le pilote écrive `waiting`. Attendre l'interruption ne garantit donc
    # pas le statut : il faut attendre le statut lui-même, sinon
    # l'assertion ci-dessous gagne une course au lieu de vérifier un fait.
    #
    # Le contrôle de la tâche 5 l'a prouvé en glissant un délai avant
    # l'écriture du statut : l'assertion rendait alors « running ». Elle ne
    # cassait jamais en pratique, seulement parce que l'écriture est rapide
    # devant l'aller-retour HTTP suivant.
    await _wait_for_status(client, project_id, account, "waiting")

    stale = (await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": "depuis-longtemps-perime", "reponse": {}},
        headers=account)).json()
    assert set(stale) == {"rejoue", "run_status"}
    # `in {...}` seul laissait passer une valeur inventée du moment qu'elle
    # figure dans l'énumération — `"done"` y était, alors que le projet
    # attend toujours sa première interruption. `advance` écrit `waiting`
    # en base AVANT de publier l'interruption (`runner.py`), et cette
    # écriture est achevée avant que `_wait_for_interaction` ne voie
    # l'interruption au point de reprise : le statut réel est donc connu et
    # vérifiable, pas seulement plausible.
    assert stale["run_status"] == "waiting"

    fresh = (await client.post(
        f"/projects/{project_id}/answer",
        json={"interaction_id": interaction["id"],
              "reponse": _answer_for(interaction)},
        headers=account)).json()
    assert set(fresh) == {"rejoue", "run_status"}


async def test_the_request_body_and_the_token_are_both_required(client, account):
    """Ni le 401 ni le 422 n'étaient couverts."""
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]

    assert (await client.post(f"/projects/{project_id}/answer",
                              json={"reponse": {}})).status_code in (401, 403)
    assert (await client.post(f"/projects/{project_id}/answer",
                              json={"reponse": {}},
                              headers=account)).status_code == 422
    assert (await client.post(f"/projects/{project_id}/answer",
                              json={"interaction_id": "", "reponse": {}},
                              headers=account)).status_code == 422
