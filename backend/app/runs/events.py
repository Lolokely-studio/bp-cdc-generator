import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

# La file d'un abonné. Deux cent cinquante-six fragments, c'est plusieurs
# secondes de rédaction : un navigateur momentanément lent a le temps de se
# rattraper, un navigateur parti ne mange pas la mémoire du processus.
SUBSCRIBER_QUEUE_SIZE = 256


@dataclass(frozen=True)
class RunEvent:
    """Un événement du §6.1. `name` est la valeur de contrat que le front
    attend au caractère près, `data` ce qu'il affiche."""

    name: str
    data: dict = field(default_factory=dict)


# Le dernier événement d'un abonné qu'on abandonne. Le front sait quoi en
# faire : se reconnecter et rappeler `/state`, comme après n'importe quelle
# coupure. C'est le §8, « aucun état ne vit dans la connexion ».
LAGGED = RunEvent("error", {
    "code": "flux_en_retard",
    "message": "Le flux a pris trop de retard. Reconnectez-vous pour "
               "retrouver l'état courant.",
    "reprenable": True,
})

# Un canal par projet, chacun portant les files de ses abonnés.
#
# CE DICTIONNAIRE VIT EN MÉMOIRE DU PROCESSUS. C'est l'hypothèse « une seule
# instance » du §9.2, et elle est écrite ici plutôt que sous-entendue : avec
# deux instances derrière un répartiteur, un navigateur abonné sur l'une ne
# verrait rien de ce que publie l'autre, sans la moindre erreur. Le jour où
# une seconde instance devient nécessaire, ce module devient un courtier
# — Redis ou `LISTEN/NOTIFY` — et c'est le seul à changer.
_channels: dict[str, set[asyncio.Queue]] = {}


def publish(project_id: str, event: RunEvent) -> None:
    """Publie sans bloquer et sans rien attendre de personne.

    Synchrone à dessein : les nœuds du graphe l'appellent au milieu d'un flux
    de tokens, et un `await` de plus par fragment coûterait une bascule de
    tâche par mot rédigé. `put_nowait` sur une file bornée suffit.
    """
    for queue in _channels.get(project_id, ()):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # L'abonné est trop lent. On ne jette pas d'événement au hasard :
            # on le coupe proprement. `_close` se charge du reste ; ici on ne
            # peut pas muter l'ensemble qu'on parcourt.
            _mark_lagged(queue)


def _mark_lagged(queue: asyncio.Queue) -> None:
    """Remplace le plus ancien élément par l'avis de retard.

    La file est pleine par définition : pour y glisser `LAGGED`, il faut
    d'abord faire de la place. On sort le plus ancien, ce qui est le moins
    mauvais choix — l'abonné sera coupé de toute façon, autant qu'il reçoive
    l'avis le plus tôt possible.
    """
    # N'ajouter LAGGED qu'une fois par file
    if not getattr(queue, '_lagged_marked', False):
        queue._lagged_marked = True
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:  # pragma: no cover — la file est pleine
            pass
        queue.put_nowait(LAGGED)


@asynccontextmanager
async def subscribe(project_id: str) -> AsyncIterator[AsyncIterator[RunEvent]]:
    """S'abonne aux événements d'un projet, le temps du bloc.

    Gestionnaire de contexte et non simple générateur : un abonné dont la
    connexion tombe doit retirer sa file, sinon `publish` continue d'y écrire
    pour un navigateur parti et le canal ne disparaît jamais.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
    _channels.setdefault(project_id, set()).add(queue)
    try:
        yield _iterate(queue)
    finally:
        subscribers = _channels.get(project_id)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                del _channels[project_id]


async def _iterate(queue: asyncio.Queue) -> AsyncIterator[RunEvent]:
    """Rend les événements jusqu'à l'avis de retard, qui clôt l'itération
    après avoir été rendu — l'abonné doit le voir passer, c'est lui qui lui
    dit de se reconnecter."""
    while True:
        event = await queue.get()
        yield event
        if event is LAGGED:
            return
