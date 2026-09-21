import pytest_asyncio

CREATION = {
    "nom": "CoachDom",
    "documents": "cdc",
    "profil_cdc": "consultation",
    "idee": "Une plateforme de coaching sportif à domicile.",
}
MOT_DE_PASSE = "motdepasse123"


@pytest_asyncio.fixture(autouse=True)
async def _fake_llm(monkeypatch):
    """Bascule le graphe sur le modèle simulé.

    `POST /projects` démarre un vrai run en tâche de fond via `start_run`.
    Sans cette bascule, `advance` appellerait la passerelle avec
    `ESQUISSE_FAKE_LLM=false` — la valeur que `tests/conftest.py` fixe pour
    toute la suite — et les fournisseurs recevraient les clés factices
    `cle-de-test`, donc de vraies requêtes réseau : exactement ce que la
    suite `not network` interdit. Même montage que
    `tests/test_runner.py::project` et `tests/test_graph.py::project`.

    Le nettoyage des runs et des pools n'est PAS ici : `tests/conftest.py`
    porte un démontage autouse qui annule les runs, ferme le point de
    reprise et ferme le pool applicatif, dans cet ordre. Le dupliquer ici
    ferait deux endroits à tenir d'accord, et c'est toujours le second
    qu'on oublie.
    """
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config

    config.settings.cache_clear()
    yield
    config.settings.cache_clear()


async def _active_account(client, label: str) -> dict:
    """Inscrit, active en base, se connecte, rend l'en-tête d'autorisation.

    Même motif que `tests/test_login.py::_register_and_activate` : le contrat
    d'API est en français — `mot_de_passe` à l'entrée, `jeton` à la sortie.

    L'adresse porte un suffixe unique, et ce n'est pas de la coquetterie :
    `migrated_db` a la portée de la SESSION, donc la base n'est pas remise à
    zéro entre deux tests d'un même fichier. Avec une adresse fixe, chaque
    test hérite des projets créés par ses prédécesseurs — constaté :
    `..._list_only_holds_the_owners_projects` voyait deux « CoachDom » et
    échouait, tout en passant lorsqu'on le lançait seul. Un test qui dépend
    de l'ordre de ses voisins est un test qu'on finit par désactiver.
    """
    from uuid import uuid4

    from app.core.db import connection

    email = f"{label}-{uuid4()}@exemple.fr"
    await client.post("/auth/register",
                      json={"email": email, "mot_de_passe": MOT_DE_PASSE})
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "update users set is_active = true where email = %s", (email,))
    response = await client.post(
        "/auth/login", json={"email": email, "mot_de_passe": MOT_DE_PASSE})
    return {"Authorization": f"Bearer {response.json()['jeton']}"}


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "projets")


async def test_creating_a_project_returns_its_header(client, account):
    response = await client.post("/projects", json=CREATION, headers=account)
    assert response.status_code == 201
    body = response.json()
    assert body["nom"] == "CoachDom"
    assert "id" in body
    # `idle` est admis, et ce n'est pas une faiblesse du test : `start_run`
    # crée une tâche et rend la main, donc la ligne peut être relue avant
    # que le pilote ait eu son tour d'ordonnanceur. Exiger `running` ici
    # ferait un test qui passe ou non selon la charge de la machine — le
    # pire genre. C'est `/state` et le flux qui disent où en est le run.
    assert body["run_status"] in {"idle", "running", "waiting"}


async def test_a_project_without_its_profile_is_refused(client, account):
    response = await client.post(
        "/projects", json={**CREATION, "profil_cdc": None}, headers=account)
    assert response.status_code == 422


async def test_the_list_only_holds_the_owners_projects(client, account):
    await client.post("/projects", json=CREATION, headers=account)

    # Un second compte, avec son propre projet.
    other_account = await _active_account(client, "intrus")
    await client.post("/projects", json={**CREATION, "nom": "PasÀToi"},
                      headers=other_account)

    names = [p["nom"] for p in (await client.get("/projects", headers=account)).json()]
    assert names == ["CoachDom"]
    assert "PasÀToi" not in names


async def test_another_users_project_is_not_found_never_forbidden(client, account):
    owner = await _active_account(client, "owner")
    project_id = (await client.post(
        "/projects", json=CREATION, headers=owner)).json()["id"]

    for chemin in (f"/projects/{project_id}", f"/projects/{project_id}/state"):
        response = await client.get(chemin, headers=account)
        assert response.status_code == 404, (
            f"{chemin} a répondu {response.status_code} : un 403 confirmerait "
            "que l'identifiant existe, ce qui suffit à énumérer les projets "
            "des autres"
        )


async def test_an_unauthenticated_call_is_refused(client):
    assert (await client.get("/projects")).status_code in (401, 403)


async def test_the_state_carries_the_plan_and_the_pending_interaction(client, account):
    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]

    # Le run tourne en tâche de fond : on lui laisse atteindre sa première
    # interruption avant de lire l'état.
    import asyncio

    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                 headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint d'interruption")

    assert state_body["plan"], "le plan est vide"
    assert state_body["curseur"] == 0
    assert state_body["interaction"]["kind"] in {"questions", "review",
                                           "inconsistencies"}
    assert "id" in state_body["interaction"]
