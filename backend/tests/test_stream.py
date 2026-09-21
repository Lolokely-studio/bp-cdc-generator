import asyncio
import contextlib
import json
from uuid import uuid4

import pytest_asyncio

from app.runs.events import RunEvent, publish
from app.projects.stream import HEARTBEAT, encode, event_stream
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
    return await _active_account(client, "flux")


def test_an_event_is_encoded_as_two_fields_and_a_blank_line():
    rendered = encode(RunEvent("token", {"text": "Bonjour"}))
    assert rendered == 'event: token\ndata: {"text": "Bonjour"}\n\n'


def test_a_newline_in_the_payload_never_breaks_the_frame():
    """Le piège du protocole : `data:` est UNE ligne. Un saut de ligne brut
    au milieu couperait la trame et le client lirait deux événements dont
    l'un est invalide."""
    rendered = encode(RunEvent("token", {"text": "deux\nlignes"}))
    body = rendered.split("\n\n")[0]
    assert body.count("\n") == 1, "la trame porte plus d'un saut de line"
    assert "\\n" in rendered, "le saut de line n'a pas été échappé"
    assert json.loads(body.split("data: ", 1)[1])["text"] == "deux\nlignes"


def test_the_heartbeat_is_a_comment_and_not_an_event():
    # Un client qui reçoit un commentaire ne déclenche aucun gestionnaire :
    # c'est ce qui permet de tenir la connexion sans polluer l'affichage.
    assert HEARTBEAT.startswith(":")
    assert HEARTBEAT.endswith("\n\n")


async def test_the_stream_delivers_what_the_run_publishes():
    """`client.stream(...)` ne peut pas éprouver ce contrat honnêtement.

    Vérifié à la lecture de `httpx.ASGITransport.handle_async_request` : un
    seul `await self.app(scope, receive, send)`, et la réponse n'est
    construite qu'une fois cet appel PLEINEMENT terminé — il n'y a aucun
    retour anticipé sur les premiers octets, contrairement à un vrai
    serveur ASGI. Un flux SSE ne se termine jamais de lui-même, c'est son
    objet ; l'appel à l'application ne reviendrait donc jamais et
    `client.stream(...)` resterait bloqué pour de bon. Constaté en le
    lançant : aucun octet, pas même les en-têtes, après plusieurs dizaines
    de secondes, alors que le même scénario sur `event_stream` nu répond en
    quelques centièmes de seconde. Ce n'est pas une course rare à
    fiabiliser — c'est un blocage systématique de ce transport de test avec
    un corps de réponse sans fin, et le contourner en tronquant le flux
    (par exemple en le noyant sous assez d'événements pour déclencher
    `LAGGED`) testerait autre chose que ce que cette fonction promet.

    Le contrat s'éprouve donc directement sur `event_stream`, la fonction
    que la route appelle une fois le propriétaire vérifié — avec le vrai
    bus (`subscribe`/`publish`), sans rien qui mime le résultat.
    """
    project_id = f"flux-integration-{uuid4()}"

    async def until_cursor(stream):
        async for frame in stream:
            if '"cursor": 42' in frame:
                return frame

    async with contextlib.aclosing(event_stream(project_id)) as stream:
        task = asyncio.ensure_future(until_cursor(stream))
        await asyncio.sleep(0.05)
        publish(project_id, RunEvent("progress", {"cursor": 42, "total": 99}))
        frame = await asyncio.wait_for(task, timeout=2)

    assert frame.startswith("event: progress\n")
    assert '"cursor": 42' in frame


async def test_another_users_stream_is_not_found(client, account):
    """Le contrôle du propriétaire doit passer AVANT d'ouvrir le flux.

    Le délai n'est pas du confort : `httpx.ASGITransport` ne rend la main
    qu'une fois l'appel ASGI PLEINEMENT terminé (vu plus haut). Si le
    contrôle passait APRÈS l'ouverture du flux, la requête ne reviendrait
    jamais — un flux SSE ne se termine pas de lui-même — et ce test
    resterait bloqué pour de bon au lieu d'échouer. Le délai transforme
    cette régression en échec net plutôt qu'en blocage silencieux de la
    suite ; il n'est jamais approché quand le contrôle est bien en place,
    la réponse 404 revient en quelques millisecondes.
    """
    owner = await _active_account(client, "flux-proprio")
    project_id = (await client.post(
        "/projects", json=CREATION, headers=owner)).json()["id"]

    async with asyncio.timeout(5):
        async with client.stream("GET", f"/projects/{project_id}/stream",
                                 headers=account) as response:
            assert response.status_code == 404
