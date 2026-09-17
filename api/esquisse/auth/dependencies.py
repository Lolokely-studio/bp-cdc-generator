from fastapi import Header, HTTPException

from esquisse.auth.bearer import bearer_token
from esquisse.db import connection
from esquisse.security import token_hash


async def active_user(authorization: str = Header(default="")) -> dict:
    """Une requête par appel, indexée sur la clé primaire de sessions.
    C'est le prix de la révocation instantanée, et il est négligeable
    aux volumes visés."""
    jeton = bearer_token(authorization)
    if not jeton:
        raise HTTPException(status_code=401, detail="jeton_absent")

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                select u.id, u.email, u.is_active
                from sessions s join users u on u.id = s.user_id
                where s.token_hash = %s
                  and s.revoked_at is null
                  and s.expires_at > now()
                """,
                (token_hash(jeton),),
            )
            ligne = await cur.fetchone()

    if not ligne:
        raise HTTPException(status_code=401, detail="session_invalide")
    if not ligne[2]:
        raise HTTPException(status_code=403, detail="compte_inactif")
    return {"id": ligne[0], "email": ligne[1]}
