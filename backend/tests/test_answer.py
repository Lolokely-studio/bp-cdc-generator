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
