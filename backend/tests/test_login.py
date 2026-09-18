import hashlib

from app.core.db import connection


async def _register_and_activate(client, email: str, active: bool) -> None:
    await client.post("/auth/register", json={"email": email, "mot_de_passe": "motdepasse123"})
    if active:
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("update users set is_active = true where email = %s", (email,))


async def test_login_returns_token(client, migrated_db):
    await _register_and_activate(client, "actif@exemple.fr", active=True)
    response = await client.post(
        "/auth/login", json={"email": "actif@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    assert response.status_code == 200
    assert len(response.json()["jeton"]) >= 43


async def test_inactive_account_rejected_with_explicit_code(client, migrated_db):
    """403 et non 401 : les identifiants sont bons, c'est l'accès qui n'est
    pas ouvert. L'interface doit pouvoir afficher le bon écran."""
    await _register_and_activate(client, "attente@exemple.fr", active=False)
    response = await client.post(
        "/auth/login", json={"email": "attente@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "compte_inactif"


async def test_wrong_password_rejected(client, migrated_db):
    await _register_and_activate(client, "mauvais@exemple.fr", active=True)
    response = await client.post(
        "/auth/login", json={"email": "mauvais@exemple.fr", "mot_de_passe": "pasbonlemotdepasse"}
    )
    assert response.status_code == 401


async def test_unknown_account_rejected_without_leak(client, migrated_db):
    response = await client.post(
        "/auth/login", json={"email": "jamais@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    assert response.status_code == 401


async def test_logout_accepts_any_case_of_the_scheme(client, migrated_db):
    """Un 204 sans révocation serait pire qu'une erreur : l'utilisateur se
    croirait déconnecté alors que son jeton resterait valable."""
    await _register_and_activate(client, "casse@exemple.fr", active=True)
    r = await client.post(
        "/auth/login", json={"email": "casse@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    token = r.json()["jeton"]
    assert (await client.post("/auth/logout", headers={"Authorization": f"bearer {token}"})).status_code == 204

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select revoked_at from sessions where token_hash = %s",
                (hashlib.sha256(token.encode()).digest(),),
            )
            assert (await cur.fetchone())[0] is not None


async def test_logout_without_header_is_harmless(client, migrated_db):
    assert (await client.post("/auth/logout")).status_code == 204
    assert (await client.post("/auth/logout", headers={"Authorization": "n importe quoi"})).status_code == 204


async def test_plaintext_token_not_stored(client, migrated_db):
    await _register_and_activate(client, "empreinte@exemple.fr", active=True)
    response = await client.post(
        "/auth/login", json={"email": "empreinte@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    token = response.json()["jeton"]
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select count(*) from sessions where token_hash = %s", (token.encode(),))
            assert (await cur.fetchone())[0] == 0
