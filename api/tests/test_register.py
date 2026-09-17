from esquisse.db import connection


async def test_register_creates_inactive_account(client, migrated_db):
    reponse = await client.post(
        "/auth/register",
        json={"email": "nouvelle@exemple.fr", "mot_de_passe": "motdepasse123"},
    )
    assert reponse.status_code == 201
    assert reponse.json()["compte_actif"] is False

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select is_active, password_hash from users where email = %s",
                ("nouvelle@exemple.fr",),
            )
            actif, stored_hash = await cur.fetchone()
    assert actif is False
    assert "motdepasse123" not in stored_hash


async def test_existing_email_responds_identically(client, migrated_db):
    """On ne révèle pas qui est inscrit : deux réponses identiques."""
    premiere = await client.post(
        "/auth/register", json={"email": "double@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    seconde = await client.post(
        "/auth/register", json={"email": "double@exemple.fr", "mot_de_passe": "autrechose456"}
    )
    assert premiere.status_code == seconde.status_code == 201
    assert premiere.json() == seconde.json()

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select count(*) from users where email = %s", ("double@exemple.fr",))
            assert (await cur.fetchone())[0] == 1


async def test_short_password_rejected(client, migrated_db):
    reponse = await client.post(
        "/auth/register", json={"email": "court@exemple.fr", "mot_de_passe": "abc"}
    )
    assert reponse.status_code == 422
