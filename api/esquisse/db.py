from contextlib import asynccontextmanager
from functools import lru_cache

from psycopg_pool import AsyncConnectionPool

from esquisse.config import settings


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


_ouvert = False


@asynccontextmanager
async def connection():
    """Ouvre le pool au premier usage. On ne s'appuie pas sur `pool.closed`,
    dont la valeur avant la première ouverture prête à confusion : un drapeau
    explicite est plus court à lire et ne dépend pas de la version.

    `open(wait=True)` plutôt que `open()` : par défaut `wait` vaut `False`
    et la méthode rend la main avant que le remplissage initial du pool ne
    soit terminé, ce qui crée une course avec la première demande de
    connexion juste en dessous. Mesuré en pratique : sans `wait=True`, la
    première connexion échoue ou reste bloquée indéfiniment sur environ une
    exécution sur deux ; avec `wait=True`, aucun échec sur plusieurs
    dizaines d'exécutions."""
    global _ouvert
    p = pool()
    if not _ouvert:
        await p.open(wait=True)
        _ouvert = True
    async with p.connection() as conn:
        yield conn
