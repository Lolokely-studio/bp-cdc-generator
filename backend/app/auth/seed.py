"""Crée un compte actif sur la base LOCALE, ou le réactive.

    uv run python -m app.auth.seed adresse@exemple.fr "un mot de passe"

Pour le développement et le parcours de bout en bout. L'activation d'un vrai
compte se fait à la main dans la base (§3.2) : ce script refuse donc tout
hôte qui n'est pas cette machine, et c'est sa seule protection. Le `.env` du
poste pointe sur la base réelle ; il faut surcharger `SUPABASE_DB_*` dans
l'environnement pour viser la base jetable.
"""

import asyncio
import sys

from app.core.config import settings
from app.core.db import close_current_pool, connection
from app.core.security import hash_password

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


async def create_active_user(email: str, password: str) -> None:
    host = settings().supabase_db_host
    if host not in LOCAL_HOSTS:
        raise SystemExit(f"refusé : {host} n'est pas une base locale")
    digest = hash_password(password)
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                insert into users (email, password_hash, is_active)
                values (%s, %s, true)
                on conflict (email) do update
                set password_hash = excluded.password_hash, is_active = true
                """,
                (email, digest),
            )


async def _main(email: str, password: str) -> None:
    try:
        await create_active_user(email, password)
    finally:
        await close_current_pool()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage : python -m app.auth.seed ADRESSE MOT_DE_PASSE")
    asyncio.run(_main(sys.argv[1], sys.argv[2]))
    print(f"compte actif : {sys.argv[1]}")
