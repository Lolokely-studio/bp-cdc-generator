from app.core.db import connection


async def test_register_creates_inactive_account(client, migrated_db):
    response = await client.post(
        "/auth/register",
        json={"email": "nouvelle@exemple.fr", "mot_de_passe": "motdepasse123"},
    )
    assert response.status_code == 201
    assert response.json()["compte_actif"] is False

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select is_active, password_hash from users where email = %s",
                ("nouvelle@exemple.fr",),
            )
            active, stored_hash = await cur.fetchone()
    assert active is False
    assert "motdepasse123" not in stored_hash


async def test_existing_email_responds_identically(client, migrated_db):
    """On ne révèle pas qui est inscrit : deux réponses identiques."""
    first = await client.post(
        "/auth/register", json={"email": "double@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    second = await client.post(
        "/auth/register", json={"email": "double@exemple.fr", "mot_de_passe": "autrechose456"}
    )
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select count(*) from users where email = %s", ("double@exemple.fr",))
            assert (await cur.fetchone())[0] == 1


async def test_short_password_rejected(client, migrated_db):
    response = await client.post(
        "/auth/register", json={"email": "court@exemple.fr", "mot_de_passe": "abc"}
    )
    assert response.status_code == 422
