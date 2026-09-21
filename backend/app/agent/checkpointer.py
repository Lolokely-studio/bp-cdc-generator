import asyncio

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings

_pool: AsyncConnectionPool | None = None
_opened = False
_lock: asyncio.Lock | None = None


def checkpointer_pool() -> AsyncConnectionPool:
    """Un pool à part de celui de l'application.

    `prepare_threshold=None` supprime les requêtes préparées côté serveur :
    ce sont un état de session, et le pooler Supabase est en mode transaction
    (§9.1). Sous faible charge le pooler rend le même backend et les requêtes
    préparées semblent tenir — un faux positif, pas une garantie.

    `row_factory=dict_row` est ce que le saver attend.
    """
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=settings().dsn,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        )
    return _pool


async def saver() -> AsyncPostgresSaver:
    """`setup()` est idempotent : il crée les tables de LangGraph au premier
    appel et ne fait rien ensuite.

    L'ouverture, elle, ne l'est pas. `open(wait=True)` appelle `wait()`, qui
    pose un événement et vérifie par assertion qu'aucun autre n'est en cours :
    deux appels concurrents à `saver()` lèvent donc une `AssertionError` au
    fond de psycopg. Le cas n'existait pas tant que seul le graphe appelait
    cette fonction, une fois par run ; la route `/state` est le premier code
    à l'appeler à chaque requête, pendant qu'un run avance en tâche de fond.

    On ouvre donc une fois, sous verrou, comme `app.core.db.connection` le
    fait pour le pool applicatif et pour la même raison.
    """
    global _opened, _lock
    pool = checkpointer_pool()
    if not _opened:
        if _lock is None:
            _lock = asyncio.Lock()
        async with _lock:
            if not _opened:
                await pool.open(wait=True)
                _opened = True
    instance = AsyncPostgresSaver(pool)
    await instance.setup()
    return instance


async def close_checkpointer() -> None:
    """Ferme le pool et remet à zéro ce qui le décrit.

    `_opened` et `_lock` repartent avec lui : un pool psycopg fermé ne se
    rouvre jamais, et le verrou est lié à la boucle d'événements qui l'a vu
    naître. Les laisser derrière soi ferait croire au prochain appel que le
    pool neuf est déjà ouvert, ou lui ferait attendre un verrou d'une boucle
    morte.
    """
    global _pool, _opened, _lock
    if _pool is not None:
        await _pool.close()
        _pool = None
    _opened = False
    _lock = None


async def purge_checkpoints(thread_id: str, keep: int = 1) -> int:
    """Supprime les points de reprise intermédiaires d'un projet terminé.

    Garde les `keep` plus récents. Ne touche pas à `checkpoint_blobs` : ses
    lignes sont partagées entre points de reprise par (channel, version), et
    en supprimer une encore référencée corromprait le point conservé — donc
    la reprise elle-même, que cette purge existe pour préserver.
    """
    pool = checkpointer_pool()
    await pool.open(wait=True)
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            delete from checkpoint_writes where thread_id = %(t)s and checkpoint_id not in (
                select checkpoint_id from checkpoints where thread_id = %(t)s
                order by checkpoint_id desc limit %(k)s
            )
            """,
            {"t": thread_id, "k": keep},
        )
        await cur.execute(
            """
            delete from checkpoints where thread_id = %(t)s and checkpoint_id not in (
                select checkpoint_id from (
                    select checkpoint_id from checkpoints where thread_id = %(t)s
                    order by checkpoint_id desc limit %(k)s
                ) as gardes
            )
            """,
            {"t": thread_id, "k": keep},
        )
        return cur.rowcount
