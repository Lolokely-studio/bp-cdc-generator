import asyncio
import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from psycopg_pool import AsyncConnectionPool

from app.core.config import settings


def _build_pool() -> AsyncConnectionPool:
    """Le pooler Supabase est déjà en mode transaction : le pool local reste
    petit, il sert à éviter le coût d'établissement TLS, pas à multiplexer.
    Ouvrir trop de connexions ici ne gagne rien et consomme le quota du
    pooler."""
    return AsyncConnectionPool(
        conninfo=settings().dsn,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True},
    )


@dataclass
class _LoopPool:
    """Un pool, le verrou qui garde son ouverture, et le fait qu'elle ait eu
    lieu. Les trois vont ensemble et vivent le temps d'une boucle."""

    pool: AsyncConnectionPool
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    ready: bool = False


# Un pool par boucle d'événements, et non un par processus.
#
# `AsyncConnectionPool` lie ses tâches de fond à la boucle active au moment de
# l'ouverture. Un pool mémoïsé pour la vie du processus survit donc à la boucle
# qui l'a ouvert : sans conséquence en production, où il n'y en a qu'une, mais
# fatal sous pytest-asyncio, qui en donne une neuve par test — la croissance du
# pool planifie alors du travail sur des tâches liées à une boucle morte et
# l'attente ne finit jamais.
#
# Le dictionnaire est faible sur ses clés : une boucle fermée s'efface d'elle
# même, et une suite de deux cents tests ne laisse pas deux cents pools.
_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopPool]" = (
    weakref.WeakKeyDictionary()
)


def _current() -> _LoopPool:
    loop = asyncio.get_running_loop()
    entry = _by_loop.get(loop)
    if entry is None:
        entry = _LoopPool(pool=_build_pool())
        _by_loop[loop] = entry
    return entry


def pool() -> AsyncConnectionPool:
    """Le pool de la boucle courante. Appelable seulement depuis du code
    asynchrone, ce qui est le cas de tous ses appelants."""
    return _current().pool


@asynccontextmanager
async def connection():
    """`open(wait=True)` protège d'une course réelle au tout premier appel :
    sans lui, `open()` rend la main avant la fin du remplissage initial et la
    première demande de connexion échoue environ une fois sur deux.

    Mais l'appeler à CHAQUE usage retourne la protection contre elle-même :
    `wait` attend `min_size` connexions disponibles, or un appelant qui en
    tient une attend alors une disponibilité qu'il est seul à pouvoir rendre.
    On attend donc une fois par pool, sous verrou, et plus jamais.
    """
    entry = _current()
    if not entry.ready:
        async with entry.lock:
            if not entry.ready:
                await entry.pool.open(wait=True)
                entry.ready = True
    async with entry.pool.connection() as conn:
        yield conn
