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
            body = await response.aread()

    assert json.loads(body) == {"detail": {"code": "projet_introuvable"}}, (
        "un 404 de chemin inexistant se lit pareil qu'un 404 de "
        "propriété : sans le corps, ce test passe même si la route a "
        "disparu — vérifié"
    )


def test_the_heartbeat_is_frequent_enough_to_hold_a_connection():
    # Le commentaire du module invoque la fenêtre d'inactivité de trente à
    # soixante secondes des intermédiaires. Le test voisin ne regarde que la
    # FORME du battement ; porter le délai à cent mille secondes laissait la
    # suite verte.
    from app.projects.stream import HEARTBEAT_SECONDS

    assert HEARTBEAT_SECONDS <= 30


async def test_the_stream_survives_its_own_heartbeats(monkeypatch):
    """Le défaut qui a justifié cette tâche, réduit à un test.

    `asyncio.wait_for(anext(it), …)` ANNULE l'`anext` à l'expiration, ce qui
    ferme le générateur asynchrone : le flux mourait après le premier
    battement, en silence, au bout de quinze secondes. Sans ce test, rien
    n'empêche quiconque de réintroduire la forme d'origine.
    """
    from app.projects import stream as st

    monkeypatch.setattr(st, "HEARTBEAT_SECONDS", 0.02)
    project_id = f"battements-{uuid4()}"
    frames = st.event_stream(project_id)

    beats = [await asyncio.wait_for(anext(frames), timeout=1) for _ in range(3)]
    assert beats == [st.HEARTBEAT] * 3

    # Et après trois battements, un vrai événement passe encore.
    publish(project_id, RunEvent("token", {"text": "vivant"}))
    frame = await asyncio.wait_for(anext(frames), timeout=1)
    assert frame.startswith("event: token")
    await frames.aclose()


async def test_the_lag_notice_reaches_the_client():
    """Le bus coupe l'abonné en retard ; encore faut-il que l'avis sorte.

    `tests/test_events.py` couvre le bus. Rien ne couvrait la traversée :
    faire avaler l'avis par `event_stream` laissait la suite verte, et le
    navigateur perdait le signal de reconnexion sur lequel repose le §8.
    """
    from app.runs.events import SUBSCRIBER_QUEUE_SIZE

    project_id = f"retard-{uuid4()}"
    frames = event_stream(project_id)
    # On amorce l'abonnement : le générateur ne s'abonne qu'à la première
    # itération, et publier avant ne toucherait personne.
    first = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    for index in range(SUBSCRIBER_QUEUE_SIZE + 50):
        publish(project_id, RunEvent("token", {"text": str(index)}))

    received = [await asyncio.wait_for(first, timeout=1)]
    with contextlib.suppress(StopAsyncIteration, asyncio.TimeoutError):
        while True:
            received.append(await asyncio.wait_for(anext(frames), timeout=1))

    assert received[-1].startswith("event: error"), (
        "l'avis de retard n'est pas parvenu au client"
    )
    assert "flux_en_retard" in received[-1]


async def test_the_response_carries_the_sse_contract(client, account):
    """La route rend-elle ce qu'un `EventSource` accepte, et écoute-t-elle le
    bon projet ?

    Trois mutations survivaient : un `media_type` en `text/plain`, la perte
    des en-têtes anti-tampon, et un abonnement à un autre projet — ce
    dernier rendant un flux silencieux pour toujours. On appelle la fonction
    de route directement : le transport de test ne sait pas conduire une
    réponse en flux, mais l'objet qu'elle construit s'inspecte.
    """
    from uuid import UUID

    from app.core.db import connection
    from app.projects.routes import stream as stream_route

    project_id = (await client.post(
        "/projects", json=CREATION, headers=account)).json()["id"]
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select user_id from projects where id = %s",
                              (UUID(project_id),))
            user_id = (await cur.fetchone())[0]

    response = await stream_route(UUID(project_id), {"id": user_id})
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    body = response.body_iterator
    pending = asyncio.ensure_future(anext(body))
    await asyncio.sleep(0)
    publish(project_id, RunEvent("progress", {"cursor": 7, "total": 9}))
    frame = await asyncio.wait_for(pending, timeout=1)
    assert frame.startswith("event: progress")
    assert '"cursor": 7' in frame, (
        "le flux n'écoute pas le projet demandé"
    )
    await body.aclose()


async def test_the_stream_releases_its_subscription(client, account):
    """Une tâche laissée par navigateur déconnecté est une fuite qui ne se
    voit qu'en production. Remplacer le `finally` par `pass` laissait la
    suite verte."""
    from app.runs import events as ev

    project_id = f"fuite-{uuid4()}"
    frames = event_stream(project_id)
    pending = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    publish(project_id, RunEvent("token", {"text": "un"}))
    await asyncio.wait_for(pending, timeout=1)

    await frames.aclose()
    await asyncio.sleep(0)
    assert project_id not in ev._channels, "le canal n'a pas été libéré"
    leaked = [t for t in asyncio.all_tasks()
              if "asend" in repr(t) and not t.done()]
    assert not leaked, f"tâche laissée derrière : {leaked}"
