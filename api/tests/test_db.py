from esquisse.config import Settings
from esquisse.db import connection


def test_env_var_gagne_sur_env_file(monkeypatch):
    """`env_file` pointe maintenant sur le `.env` de la racine du dépôt, qui
    contient les identifiants Supabase de production. Ce test prouve qu'une
    variable d'environnement déjà posée (ici par l'affectation ferme de
    conftest.py) l'emporte toujours sur ce fichier : on pose une valeur
    fantaisiste et on vérifie qu'elle est bien celle retenue. On appelle
    `Settings()` directement, pas `settings()` : ce dernier est mémoïsé et ne
    relirait pas l'environnement à un second appel."""
    monkeypatch.setenv("SUPABASE_DB_NAME", "valeur_fantaisiste_qui_ne_peut_pas_venir_du_env_file")
    reglages = Settings()
    assert reglages.supabase_db_name == "valeur_fantaisiste_qui_ne_peut_pas_venir_du_env_file"


async def test_connexion_rend_une_session_utilisable():
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
