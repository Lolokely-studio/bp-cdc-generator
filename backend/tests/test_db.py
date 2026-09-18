from app.core.db import connection


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


async def test_two_connections_can_be_held_at_once(migrated_db):
    """Le défaut d'origine tenait à deux causes : `open(wait=True)` à chaque
    appel, et un pool mémoïsé pour la vie du processus survivant à la boucle
    qui l'avait ouvert. Huit secondes suffisent largement — le blocage était
    infini."""
    import asyncio

    from app.core.db import connection

    async with connection() as first:
        async with first.cursor() as cur:
            await cur.execute("select 1")
        async with asyncio.timeout(8):
            async with connection() as second:
                async with second.cursor() as cur:
                    await cur.execute("select 2")
                    assert (await cur.fetchone())[0] == 2
