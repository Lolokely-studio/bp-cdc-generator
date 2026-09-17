from datetime import datetime, timedelta, timezone
from uuid import UUID


async def create_user(conn, email: str, password_digest: str) -> UUID | None:
    """Rend l'identifiant, ou None si l'adresse est déjà prise.
    L'appelant répond la même chose dans les deux cas."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into users (email, password_hash) values (%s, %s)
            on conflict (email) do nothing
            returning id
            """,
            (email, password_digest),
        )
        ligne = await cur.fetchone()
    return ligne[0] if ligne else None


async def user_by_email(conn, email: str) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, email, password_hash, is_active from users where email = %s",
            (email,),
        )
        ligne = await cur.fetchone()
    if not ligne:
        return None
    return {"id": ligne[0], "email": ligne[1], "password_hash": ligne[2], "is_active": ligne[3]}


async def open_session(conn, user_id: UUID, token_digest: bytes, ttl_heures: int) -> None:
    expire = datetime.now(timezone.utc) + timedelta(hours=ttl_heures)
    async with conn.cursor() as cur:
        await cur.execute(
            "insert into sessions (token_hash, user_id, expires_at) values (%s, %s, %s)",
            (token_digest, user_id, expire),
        )
        await cur.execute("update users set last_login_at = now() where id = %s", (user_id,))


async def revoke_session(conn, token_digest: bytes) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "update sessions set revoked_at = now() where token_hash = %s and revoked_at is null",
            (token_digest,),
        )
