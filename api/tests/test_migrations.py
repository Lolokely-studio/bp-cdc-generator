from esquisse.db import connection


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
