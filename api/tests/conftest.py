import os
import subprocess
from pathlib import Path

import pytest

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
    subprocess.run(["uv", "run", "alembic", "downgrade", "base"], cwd=api_root, check=False)
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=api_root, check=True)
    return True
