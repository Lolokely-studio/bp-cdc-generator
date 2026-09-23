from uuid import uuid4

import pytest

from app.auth.seed import create_active_user
from app.core import config


async def test_the_script_creates_an_account_that_can_log_in(client, migrated_db):
    email = f"seed-{uuid4()}@exemple.fr"
    await create_active_user(email, "motdepasse-du-script")
    response = await client.post(
        "/auth/login", json={"email": email, "mot_de_passe": "motdepasse-du-script"})
    assert response.status_code == 200


async def test_running_it_again_resets_the_password_and_reactivates(client, migrated_db):
    from app.core.db import connection

    email = f"seed-{uuid4()}@exemple.fr"
    await create_active_user(email, "premier-mot-de-passe")
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("update users set is_active = false where email = %s", (email,))
    await create_active_user(email, "second-mot-de-passe")

    ok = await client.post("/auth/login",
                           json={"email": email, "mot_de_passe": "second-mot-de-passe"})
    old = await client.post("/auth/login",
                            json={"email": email, "mot_de_passe": "premier-mot-de-passe"})
    assert ok.status_code == 200 and old.status_code == 401
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select count(*) from users where email = %s", (email,))
            assert (await cur.fetchone())[0] == 1


async def test_the_script_refuses_a_remote_database(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_HOST", "aws-0-eu-west-3.pooler.supabase.com")
    config.settings.cache_clear()
    try:
        with pytest.raises(SystemExit):
            await create_active_user(f"seed-{uuid4()}@exemple.fr", "motdepasse-distant")
    finally:
        config.settings.cache_clear()
