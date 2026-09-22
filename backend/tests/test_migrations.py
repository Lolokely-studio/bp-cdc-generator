import subprocess
from pathlib import Path

from app.core.db import connection


async def test_migration_0004_mounts_and_unmounts_idee_cleanly(migrated_db):
    """Constat 4 de la revue finale, dernier des sept tests : la migration
    0004 doit monter et descendre proprement. `migrated_db` a déjà appliqué
    `head` pour toute la suite ; on vérifie ici que `idee` apparaît, que le
    retour arrière la retire, et que remonter la rétablit."""
    api_root = Path(__file__).resolve().parents[1]

    async def _has_idee_column() -> bool:
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "select column_name from information_schema.columns "
                    "where table_name = 'projects' and column_name = 'idee'")
                return (await cur.fetchone()) is not None

    assert await _has_idee_column(), "`head` inclut 0004 : `idee` doit exister"

    try:
        subprocess.run(["uv", "run", "alembic", "downgrade", "0003"],
                       cwd=api_root, check=True, capture_output=True, text=True)
        assert not await _has_idee_column(), (
            "le retour arrière de la migration 0004 n'a pas retiré `idee`"
        )
    finally:
        # Remonter dans tous les cas : une base laissée sous `head` ferait
        # échouer les tests suivants de la suite, sans rapport avec celui-ci.
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"],
                       cwd=api_root, check=True, capture_output=True, text=True)

    assert await _has_idee_column(), (
        "remonter jusqu'à `head` n'a pas rétabli `idee`"
    )


async def test_account_tables_exist(migrated_db):
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                select table_name from information_schema.tables
                where table_schema = 'public' order by table_name
            """)
            tables = {r[0] for r in await cur.fetchall()}
    assert {"users", "sessions"} <= tables


async def test_is_active_defaults_to_false(migrated_db):
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash) values (%s, %s) returning is_active",
                ("defaut@exemple.fr", "x"),
            )
            assert (await cur.fetchone())[0] is False
            await cur.execute("delete from users where email = %s", ("defaut@exemple.fr",))
