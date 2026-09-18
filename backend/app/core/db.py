from contextlib import asynccontextmanager
from functools import lru_cache

from psycopg_pool import AsyncConnectionPool

from app.core.config import settings


@lru_cache
def pool() -> AsyncConnectionPool:
    """Le pooler Supabase est déjà en mode transaction : le pool local
    reste petit, il sert à éviter le coût d'établissement TLS, pas à
    multiplexer. Ouvrir trop de connexions ici ne gagne rien et
    consomme le quota du pooler."""
    return AsyncConnectionPool(
        conninfo=settings().dsn,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True},
    )


@asynccontextmanager
async def connection():
    """`open` est idempotent et prend un verrou interne : l'appeler ici garde la
    fonction autonome, y compris dans les tests, où le transport ASGI de httpx
    n'exécute pas le cycle de vie.

    `open(wait=True)` plutôt que `open()` : par défaut `wait` vaut `False`
    et la méthode rend la main avant que le remplissage initial du pool ne
    soit terminé, ce qui crée une course avec la première demande de
    connexion juste en dessous. Mesuré en pratique : sans `wait=True`, la
    première connexion échoue ou reste bloquée indéfiniment sur environ une
    exécution sur deux ; avec `wait=True`, aucun échec sur plusieurs
    dizaines d'exécutions."""
    connection_pool = pool()
    await connection_pool.open(wait=True)
    async with connection_pool.connection() as conn:
        yield conn
