from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings

_pool: AsyncConnectionPool | None = None


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
    appel et ne fait rien ensuite."""
    pool = checkpointer_pool()
    await pool.open(wait=True)
    instance = AsyncPostgresSaver(pool)
    await instance.setup()
    return instance


async def close_checkpointer() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


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
