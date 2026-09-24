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
        # `prepare_threshold=None` désactive les requêtes préparées.
        # psycopg3 en prépare une après sa cinquième exécution ; derrière le
        # pooler de transactions de Supabase, chaque transaction peut
        # atterrir sur une connexion serveur différente, où l'instruction
        # préparée n'existe pas — `InvalidSqlStatementName: prepared
        # statement "_pg3_0" does not exist`, à la sixième requête, sur la
        # vérification du compte que fait chaque appel authentifié.
        #
        # Aucun test ne le voit : `tests/conftest.py` pointe sur le Postgres
        # local en direct (port 5433), sans pooler, où les requêtes
        # préparées fonctionnent.
        kwargs={"autocommit": True, "prepare_threshold": None},
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


async def close_current_pool() -> None:
    """Ferme le pool de la boucle courante et oublie son entrée.

    Oublier l'entrée n'est pas facultatif : un pool psycopg fermé ne se
    rouvre jamais, donc le laisser dans le dictionnaire condamnerait tout
    appel ultérieur sur la même boucle. On le retire, et le prochain appel en
    construira un neuf.

    Cette fonction existe pour les tests. En production, c'est le cycle de vie
    de l'application qui ferme le pool — mais ce cycle ne tourne jamais sous
    pytest : `httpx.ASGITransport` n'exécute pas les événements de cycle de
    vie ASGI, ce qui se lit à sa signature, dépourvue de paramètre
    `lifespan`. Les tâches de fond du pool survivaient donc à chaque test
    touchant la base, et leur annulation en masse à la fermeture de la boucle
    faisait récurser `Task.cancel()` dans les futures chaînées de psycopg
    jusqu'à la `RecursionError`. Celle-ci était avalée par le gestionnaire
    d'exceptions par défaut d'asyncio, donc invisible : la suite pendait sans
    rien dire.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover — appelée depuis du code async
        return
    entry = _by_loop.pop(loop, None)
    if entry is not None and entry.ready:
        await entry.pool.close()
