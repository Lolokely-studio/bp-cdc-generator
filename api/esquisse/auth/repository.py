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
