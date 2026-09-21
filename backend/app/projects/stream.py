import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

from app.runs.events import RunEvent, subscribe

# Un commentaire SSE : le client le reçoit et ne déclenche aucun
# gestionnaire. C'est ce qui tient la connexion ouverte à travers les
# intermédiaires qui coupent au bout de trente à soixante secondes
# d'inactivité — et une section peut s'écrire sans rien publier pendant
# plusieurs secondes.
HEARTBEAT = ": battement\n\n"
HEARTBEAT_SECONDS = 15


def encode(event: RunEvent) -> str:
    """Une trame SSE : un champ par ligne, une ligne vide pour terminer.

    `json.dumps` n'est pas un détail : `data:` est UNE ligne, et un saut de
    ligne brut dans le texte rédigé couperait la trame en deux. Le client
    lirait alors un événement tronqué suivi d'un fragment invalide, sans
    erreur visible côté serveur.
    """
    return f"event: {event.name}\ndata: {json.dumps(event.data)}\n\n"


async def event_stream(project_id: str) -> AsyncIterator[str]:
    """Les événements du projet, plus un battement quand rien ne vient.

    PAS `asyncio.wait_for(anext(iterator), ...)` : ça annule l'attente en
    cours dès l'expiration du délai, et annuler un `anext()` suspendu
    injecte une `CancelledError` dans le générateur asynchrone sous-jacent
    (`_iterate`, dans `app.runs.events`). Une exception non rattrapée qui
    traverse le cadre d'un générateur le CLÔT — comme n'importe quel
    générateur. Constaté à l'exécution : le premier battement passe, mais le
    `anext()` suivant tombe alors sur un générateur déjà fermé et lève tout
    de suite `StopAsyncIteration` — `event_stream` rend la main pour de bon
    après un seul battement, et le flux se coupe en silence pour un client
    qui tourne encore. On garde donc la MÊME tâche `anext()` d'un tour à
    l'autre : `asyncio.wait` avec un délai n'annule rien quand il expire,
    contrairement à `wait_for`, et on ne l'annule qu'en sortant pour de bon.
    """
    async with subscribe(project_id) as events:
        iterator = events.__aiter__()
        pending = asyncio.ensure_future(anext(iterator))
        try:
            while True:
                done, _pending = await asyncio.wait(
                    {pending}, timeout=HEARTBEAT_SECONDS)
                if not done:
                    yield HEARTBEAT
                    continue
                try:
                    event = pending.result()
                except StopAsyncIteration:
                    # L'abonné a été abandonné pour retard : l'avis est déjà
                    # parti, il n'y a plus rien à envoyer.
                    return
                pending = asyncio.ensure_future(anext(iterator))
                yield encode(event)
        finally:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError,
                                     StopAsyncIteration):
                await pending
