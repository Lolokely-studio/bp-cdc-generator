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
    # Ce que la création a réellement écrit. Sans ces lignes, intervertir
    # `profil_cdc` et `profil_bp` à l'insertion laissait les 405 tests verts
    # — alors que l'étoile de `create_project` existe précisément pour
    # empêcher cette confusion au site d'appel.
    assert body["documents"] == CREATION["documents"]
    assert body["profil_cdc"] == CREATION["profil_cdc"]
    assert body["profil_bp"] is None
    # Les horodatages valent sur TOUTES les routes qui rendent ce schéma,
    # pas seulement sur la liste.
    assert body["created_at"] and body["updated_at"]
    # Le jeu de clés exact : `thread_id` et `user_id` ne sortent jamais. Ils
    # sont filtrés deux fois aujourd'hui — par `response_model` et parce que
    # pydantic ignore les clés en trop — mais deux coïncidences ne font pas
    # un contrat.
    assert set(body) == {"id", "nom", "documents", "profil_cdc", "profil_bp",
                         "run_status", "created_at", "updated_at"}


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
        assert response.json() == {"detail": {"code": "projet_introuvable"}}, (
            "le corps distingue « n'existe pas » de « pas à vous » : c'est "
            "un oracle d'énumération complet, exactement ce que le 404 "
            "existe pour fermer"
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


async def test_an_unknown_project_answers_exactly_like_someone_elses(client, account):
    """Le code de statut ne suffit pas à fermer le trou d'énumération.

    Vérifié par mutation : un corps qui distingue les deux sortes d'absence
    laissait les six tests verts, alors qu'il suffit à énumérer les projets
    des autres.
    """
    from uuid import uuid4

    owner = await _active_account(client, "corps-404")
    someone_elses = (await client.post("/projects", json=CREATION,
                                       headers=owner)).json()["id"]
    unknown = str(uuid4())

    bodies = []
    for candidate in (someone_elses, unknown):
        for path in (f"/projects/{candidate}", f"/projects/{candidate}/state"):
            response = await client.get(path, headers=account)
            assert response.status_code == 404
            bodies.append(response.json())
    assert all(b == bodies[0] for b in bodies), (
        "les deux sortes d'absence ne se répondent pas à l'identique"
    )


async def test_the_header_status_agrees_with_the_state(client, account):
    """`run_status` pilote toute l'interface, et rien ne le regardait.

    Une valeur figée à `idle` dans le schéma laissait les 405 tests verts.
    """
    import asyncio

    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    for _ in range(100):
        header = (await client.get(f"/projects/{project_id}",
                                   headers=account)).json()
        if header["run_status"] == "waiting":
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("l'entête n'a jamais annoncé `waiting`")

    state_body = (await client.get(f"/projects/{project_id}/state",
                                   headers=account)).json()
    assert state_body["interaction"] is not None, (
        "l'entête annonce `waiting` alors que rien n'attend de réponse"
    )


async def test_the_state_interaction_id_is_the_one_langgraph_gave(client, account):
    """Toute l'idempotence de la tâche 5 repose sur cet identifiant.

    Le test précédent ne vérifiait que sa PRÉSENCE : une constante y passait,
    et la suite entière restait verte. On le compare donc à la source.
    """
    import asyncio
    from uuid import UUID

    from app.agent.graph import compiled_graph
    from app.core.db import connection

    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    for _ in range(100):
        state_body = (await client.get(f"/projects/{project_id}/state",
                                       headers=account)).json()
        if state_body["interaction"] is not None:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais atteint d'interruption")

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select thread_id from projects where id = %s",
                              (UUID(project_id),))
            thread_id = (await cur.fetchone())[0]
    graph = await compiled_graph()
    snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})

    assert state_body["interaction"]["id"] == snapshot.interrupts[0].id


async def test_a_both_document_project_carries_the_two_profiles(client, account):
    """`profil_bp` n'était renseigné nulle part dans toute la suite.

    La moitié du validateur de `ProjectCreate` et la moitié de `plan_for`
    n'étaient donc jamais traversées par HTTP. Un projet `both` produit aussi
    le plan le plus long, ce qui exerce le chemin où le curseur enjambe deux
    catalogues.
    """
    creation = {**CREATION, "nom": "LesDeux", "documents": "both",
                "profil_bp": "banque"}
    body = (await client.post("/projects", json=creation,
                              headers=account)).json()
    assert body["profil_cdc"] == "consultation"
    assert body["profil_bp"] == "banque"

    # Le plan n'existe qu'à partir du premier point de reprise écrit par le
    # run de fond ; juste après le `POST`, la tâche peut ne pas encore avoir
    # eu son tour d'ordonnanceur et `/state` répond alors un plan vide, pas
    # un plan à un seul document. Même montage de sondage que
    # `test_the_state_carries_the_plan_and_the_pending_interaction`.
    import asyncio

    for _ in range(100):
        state_body = (await client.get(f"/projects/{body['id']}/state",
                                       headers=account)).json()
        if state_body["plan"]:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("le run n'a jamais écrit son plan")

    documents = {ref["document"] for ref in state_body["plan"]}
    assert documents == {"cdc", "bp"}, (
        "un projet `both` doit porter les deux documents à son plan"
    )


async def test_the_list_is_ordered_most_recently_modified_first(client, account):
    """Le tri est la seule raison d'être de l'index que la docstring invoque,
    et rien ne le vérifiait.

    Les horodatages sont posés à la main : les runs de fond écrivent
    `updated_at` à leur rythme, et un test qui dépend de leur ordonnancement
    passerait selon la machine.
    """
    from uuid import UUID

    from app.core.db import connection

    first = (await client.post("/projects", json={**CREATION, "nom": "Ancien"},
                               headers=account)).json()["id"]
    second = (await client.post("/projects", json={**CREATION, "nom": "Recent"},
                                headers=account)).json()["id"]
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "update projects set updated_at = now() - interval '1 hour' "
                "where id = %s", (UUID(second),))
            await cur.execute(
                "update projects set updated_at = now() where id = %s",
                (UUID(first),))

    names = [p["nom"] for p in (await client.get("/projects",
                                                 headers=account)).json()]
    assert names.index("Ancien") < names.index("Recent"), (
        "la liste n'est pas triée par date de modification décroissante"
    )
