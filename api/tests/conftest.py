import os
import subprocess
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from esquisse.app import create_app

# Affectation ferme (et non `setdefault`) : le `.env` à la racine du dépôt
# contient les identifiants de la base Supabase de production, et un
# développeur peut avoir ces variables SUPABASE_DB_* déjà exportées dans son
# shell. Avec `setdefault`, ces valeurs existantes passeraient au travers et
# la suite de tests s'exécuterait alors contre la base réelle. L'affectation
# ferme écrase toute valeur préexistante et garantit que les tests ne parlent
# jamais qu'à la base jetable de docker-compose.
os.environ["SUPABASE_DB_HOST"] = "localhost"
os.environ["SUPABASE_DB_PORT"] = "5433"
os.environ["SUPABASE_DB_USER"] = "esquisse"
os.environ["SUPABASE_DB_PASSWORD"] = "esquisse"
os.environ["SUPABASE_DB_NAME"] = "esquisse_test"


@pytest.fixture(scope="session")
def migrated_db():
    """Applique les migrations sur la base jetable avant la suite de tests.
    Même chemin qu'en production : si une migration casse, les tests cassent.

    Le sous-processus doit s'exécuter depuis `api/` (là où vit `alembic.ini`),
    jamais depuis le répertoire courant du lancement de pytest : on calcule
    ce chemin à partir de `__file__` plutôt que de le supposer.
    """
    api_root = Path(__file__).resolve().parents[1]

    # `check=False` seul masquerait un vrai échec : une base laissée dans un
    # état partiel par une exécution interrompue produirait au tour suivant une
    # erreur peu diagnostique, voire des tests verts sur un schéma périmé. On
    # distingue donc « rien à annuler » d'« annulation en échec ».
    retour = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "base"],
        cwd=api_root, check=False, capture_output=True, text=True,
    )
    if retour.returncode != 0 and "Can't locate revision" not in retour.stderr:
        raise RuntimeError(
            "Le retour arrière des migrations a échoué, la base de test est "
            f"peut-être dans un état partiel :\n{retour.stderr}"
        )

    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=api_root, check=True)
    return True


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
