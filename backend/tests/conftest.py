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

# Les clés des fournisseurs de modèles subissent le même traitement, pour la
# même raison : le `.env` en contient de vraies. Aucun test de la suite
# ordinaire ne joint un fournisseur, mais une valeur fixe rend aussi les
# assertions déterministes — sans elle, « ce fournisseur est configuré »
# dépendrait du poste sur lequel la suite tourne.
#
# L'exception est la campagne marquée `network`, qui vérifie à la demande que
# les URL de base et les noms de modèles sont encore valides. Elle réclame
# les vraies clés et se lance explicitement :
#     ESQUISSE_NETWORK_TESTS=1 uv run pytest -m network
if os.environ.get("ESQUISSE_NETWORK_TESTS") != "1":
    for _provider_key in (
        "GEMINI_API_KEY",
        "MISTRAL_AI_API_KEY",
        "OPENROUTER_API_KEY",
        "NVIDIA_API_KEY",
        "GROQ_CLOUD_API_KEY",
    ):
        os.environ[_provider_key] = "cle-de-test"

# Même raison pour le drapeau du modèle simulé : un développeur qui laisse
# `ESQUISSE_FAKE_LLM=true` dans son `.env` ferait tourner une autre suite que
# celle de l'intégration continue.
os.environ["ESQUISSE_FAKE_LLM"] = "false"

# Les imports de `app` viennent APRÈS les affectations ci-dessus. Aujourd'hui
# `settings()` est paresseux et mémoïsé, donc l'ordre ne change rien — mais il
# suffirait qu'un module appelle `settings()` à l'import pour que la configuration
# se fige sur le `.env` de production. On ne fait pas reposer sur la chance ce que
# l'ordre garantit.
import httpx
import pytest_asyncio
from app.main import create_app


@pytest.fixture(scope="session")
def migrated_db():
    """Applique les migrations sur la base jetable avant la suite de tests.
    Même chemin qu'en production : si une migration casse, les tests cassent.

    Le sous-processus doit s'exécuter depuis `backend/` (là où vit `alembic.ini`),
    jamais depuis le répertoire courant du lancement de pytest : on calcule
    ce chemin à partir de `__file__` plutôt que de le supposer.
    """
    api_root = Path(__file__).resolve().parents[1]

    # `check=False` seul masquerait un vrai échec : une base laissée dans un
    # état partiel par une exécution interrompue produirait au tour suivant une
    # erreur peu diagnostique, voire des tests verts sur un schéma périmé. On
    # distingue donc « rien à annuler » d'« annulation en échec ».
    result = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "base"],
        cwd=api_root, check=False, capture_output=True, text=True,
    )
    if result.returncode != 0 and "Can't locate revision" not in result.stderr:
        raise RuntimeError(
            "Le retour arrière des migrations a échoué, la base de test est "
            f"peut-être dans un état partiel :\n{result.stderr}"
        )

    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=api_root, check=True)
    return True


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_rate_limit():
    """Le compteur vit dans le processus : sans remise à zéro, un test
    qui consomme la limite fait échouer le suivant."""
    from app.auth import routes
    routes._account_limiter.reset()
    yield


@pytest.fixture(autouse=True)
def _fresh_pacers():
    """L'espacement par seconde vit dans le processus, et le verrou d'un
    `Pacer` se lie à la boucle d'événements de son premier appel. pytest-asyncio
    en donne une neuve par test : sans remise à zéro, un test réutiliserait un
    verrou lié à une boucle fermée et échouerait sans rapport avec son objet."""
    from app.llm.budget import reset_pacers

    reset_pacers()
    yield
