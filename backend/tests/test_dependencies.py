from app.core.db import connection


async def _token_for(client, email: str) -> str:
    await client.post("/auth/register", json={"email": email, "mot_de_passe": "motdepasse123"})
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("update users set is_active = true where email = %s", (email,))
    r = await client.post("/auth/login", json={"email": email, "mot_de_passe": "motdepasse123"})
    return r.json()["jeton"]


async def test_me_returns_account(client, migrated_db):
    token = await _token_for(client, "moi@exemple.fr")
    r = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "moi@exemple.fr"


async def test_missing_token_rejected(client, migrated_db):
    assert (await client.get("/me")).status_code == 401


async def test_unknown_token_rejected(client, migrated_db):
    r = await client.get("/me", headers={"Authorization": "Bearer nimportequoi"})
    assert r.status_code == 401


async def test_deactivation_takes_effect_immediately(client, migrated_db):
    """Le cœur du choix des jetons opaques : le drapeau est basculé à la
    main dans la base, et le jeton déjà émis cesse de valoir aussitôt.
    Un JWT resterait valable jusqu'à son expiration."""
    token = await _token_for(client, "coupe@exemple.fr")
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/me", headers=headers)).status_code == 200

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("update users set is_active = false where email = %s", ("coupe@exemple.fr",))

    assert (await client.get("/me", headers=headers)).status_code == 403


async def test_logout_invalidates_token(client, migrated_db):
    token = await _token_for(client, "sortie@exemple.fr")
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.post("/auth/logout", headers=headers)).status_code == 204
    assert (await client.get("/me", headers=headers)).status_code == 401
