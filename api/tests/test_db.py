from esquisse.db import connection


async def test_connection_yields_usable_session():
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select 1")
            assert (await cur.fetchone())[0] == 1


async def test_set_local_applies_within_transaction():
    """Le pooler est en mode transaction : SET LOCAL est le seul mécanisme
    sûr pour porter une valeur. Ce test fixe cette contrainte dans le code."""
    async with connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("set local esquisse.test = 'valeur'")
                await cur.execute("select current_setting('esquisse.test', true)")
                assert (await cur.fetchone())[0] == "valeur"
