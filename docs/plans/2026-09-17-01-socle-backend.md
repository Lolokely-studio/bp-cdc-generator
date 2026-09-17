# Socle backend — plan d'implémentation

> **Pour les agents d'exécution :** SOUS-COMPÉTENCE REQUISE — utiliser
> `superpowers:subagent-driven-development` (recommandé) ou
> `superpowers:executing-plans` pour dérouler ce plan tâche par tâche.
> Les étapes utilisent des cases à cocher (`- [ ]`) pour le suivi.

**But :** une API FastAPI qui démarre, une base migrée, des comptes dont l'accès est conditionné à une activation manuelle, et un cloisonnement des projets vérifié par un test.

**Architecture :** FastAPI en asynchrone, `psycopg` 3 avec un pool asynchrone vers le pooler Supabase en mode transaction. Les migrations passent par Alembic sur un moteur synchrone séparé — c'est le seul endroit où SQLAlchemy est utilisé, l'application n'écrit que du SQL. Les sessions sont des jetons opaques vérifiés en base, pas des JWT, parce que le drapeau d'activation doit prendre effet immédiatement.

**Pile :** Python 3.12, uv, FastAPI, uvicorn, psycopg[binary,pool] 3, Alembic, argon2-cffi, pydantic-settings, pytest, pytest-asyncio.

**Spec :** [../spec-implementation.md](../spec-implementation.md) — §2 modèle de données, §3 comptes et sessions, §9 contraintes d'exploitation, §10 tests, §11 configuration.

## Contraintes globales

- **Gestionnaire de paquets : `uv`, jamais `pip`.** `pyproject.toml` et `uv.lock` sont versionnés. Toute commande passe par `uv run`.
- **Python 3.12.**
- **Aucune variable de session PostgreSQL.** Le pooler est en mode transaction : ce qui doit valoir pour une requête se pose en `SET LOCAL`, dans la transaction. Une variable posée hors transaction disparaît sans erreur.
- **Aucun test ne joint un vrai fournisseur de modèle ni la base de production.** Les tests utilisent une base PostgreSQL locale jetable.
- **Un projet qui n'appartient pas à l'utilisateur répond `404`, jamais `403`.** On ne révèle pas l'existence de ce qu'on ne possède pas.
- **Les identifiants du code sont en anglais** : fonctions, classes, fixtures, modules, fichiers, mais aussi variables et constantes. **Les commentaires, les docstrings et la documentation restent en français.** Les noms de colonnes SQL restent tels qu'ils sont définis au §2.1 de la spec, et les codes d'erreur d'API (`compte_inactif`, `identifiants_invalides`) aussi : ce sont des valeurs de contrat que l'interface lit.

---

## Structure des fichiers

```
api/
├── pyproject.toml              Dépendances et configuration des outils
├── uv.lock                     Verrou, versionné
├── alembic.ini                 Configuration Alembic
├── migrations/
│   ├── env.py                  Moteur synchrone pour les migrations
│   └── versions/               Révisions
├── esquisse/
│   ├── __init__.py
│   ├── config.py               Réglages lus dans l'environnement
│   ├── db.py                   Pool de connexions asynchrone
│   ├── app.py                  Application FastAPI, /health
│   ├── security.py             Empreintes de mot de passe, jetons
│   ├── rate_limit.py           Limitation de débit en mémoire
│   ├── safety.py               Refus des migrations hors base locale
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── routes.py           /auth/register, /auth/login, /auth/logout, /me
│   │   ├── repository.py            Accès SQL aux tables users et sessions
│   │   └── dependencies.py     Dépendance FastAPI « utilisateur actif »
│   └── projects/
│       ├── __init__.py
│       └── repository.py            project_for_user, seul accès à la table
└── tests/
    ├── conftest.py             Base jetable, client HTTP, utilisateurs
    ├── test_health.py
    ├── test_config.py
    ├── test_safety.py
    ├── test_db.py
    ├── test_security.py
    ├── test_register.py
    ├── test_login.py
    ├── test_dependencies.py
    ├── test_rate_limit.py
    └── test_isolation.py
```

Chaque module a une responsabilité unique. `repository.py` est le seul endroit où l'on écrit du SQL pour un domaine donné : c'est ce qui rend vérifiable, à la tâche 8, qu'aucune requête ne contourne le cloisonnement.

---

## Tâche 1 : squelette du projet et santé de l'application

**Fichiers :**
- Créer : `api/pyproject.toml`
- Créer : `api/esquisse/__init__.py`
- Créer : `api/esquisse/app.py`
- Créer : `api/tests/__init__.py`
- Test : `api/tests/test_health.py`

**Interfaces :**
- Consomme : rien.
- Produit : `esquisse.app.create_app() -> FastAPI` et l'instance de module `esquisse.app.app`. Toutes les tâches suivantes montent leurs routes sur cette application.

- [ ] **Étape 1 : créer le projet avec uv**

```bash
mkdir -p api && cd api
uv init --python 3.12 --no-workspace --name esquisse
uv add "fastapi>=0.115" "uvicorn[standard]>=0.32"
uv add --dev "pytest>=8" "pytest-asyncio>=0.24" "httpx>=0.27"
```

- [ ] **Étape 2 : configurer pytest dans `pyproject.toml`**

Ajouter à `api/pyproject.toml` :

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Étape 3 : écrire le test qui échoue**

`api/tests/test_health.py` :

```python
import httpx
import pytest
from esquisse.app import create_app


async def test_health_returns_ok():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.get("/health")
    assert reponse.status_code == 200
    assert reponse.json() == {"statut": "ok"}
```

- [ ] **Étape 4 : lancer le test et vérifier qu'il échoue**

Lancer : `cd api && uv run pytest tests/test_health.py -v`
Attendu : ÉCHEC, `ModuleNotFoundError: No module named 'esquisse.app'`

- [ ] **Étape 5 : écrire l'implémentation minimale**

`api/esquisse/__init__.py` : fichier vide.

`api/esquisse/app.py` :

```python
from fastapi import FastAPI


def create_app() -> FastAPI:
    """Construit l'application. Une fonction et non un module-niveau :
    les tests en créent une par cas, sans état partagé."""
    app = FastAPI(title="Esquisse", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Sonde de réveil. L'hébergement gratuit s'endort après quinze
        minutes ; l'interface appelle cette route et affiche un écran
        d'attente le temps du redémarrage."""
        return {"statut": "ok"}

    return app


app = create_app()
```

`api/tests/__init__.py` : fichier vide.

- [ ] **Étape 6 : lancer le test et vérifier qu'il passe**

Lancer : `cd api && uv run pytest tests/test_health.py -v`
Attendu : SUCCÈS

- [ ] **Étape 7 : vérifier que le serveur démarre**

Lancer : `cd api && uv run uvicorn esquisse.app:app --port 8000`
Attendu : le serveur démarre ; `curl -s localhost:8000/health` renvoie `{"statut":"ok"}`. Arrêter avec Ctrl-C.

- [ ] **Étape 8 : commiter**

```bash
git add api/pyproject.toml api/uv.lock api/esquisse api/tests
git commit -m "feat(api): squelette FastAPI et sonde de santé"
```

---

## Tâche 2 : configuration et pool de connexions

**Fichiers :**
- Créer : `api/esquisse/config.py`
- Créer : `api/esquisse/db.py`
- Créer : `api/tests/conftest.py`
- Créer : `docker-compose.yml` (racine du dépôt)
- Test : `api/tests/test_db.py` (connexion) et `api/tests/test_config.py` (réglages)

**Interfaces :**
- Consomme : rien.
- Produit :
  - `esquisse.config.Settings` (pydantic-settings) avec `dsn: str`, `session_ttl_hours: int`, `fake_llm: bool`
  - `esquisse.config.settings() -> Settings`, mémoïsé
  - `esquisse.db.pool() -> AsyncConnectionPool`
  - `esquisse.db.connection()` — gestionnaire de contexte asynchrone qui rend une connexion du pool
  - Toutes les tâches suivantes obtiennent leurs connexions par `connection()`.

- [ ] **Étape 1 : ajouter les dépendances**

```bash
cd api
uv add "psycopg[binary,pool]>=3.2" "pydantic-settings>=2.6"
```

- [ ] **Étape 2 : créer la base de test locale**

`docker-compose.yml` à la racine du dépôt :

```yaml
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_PASSWORD: esquisse
      POSTGRES_USER: esquisse
      POSTGRES_DB: esquisse_test
    ports: ["5433:5432"]
```

Lancer : `docker compose up -d db`

- [ ] **Étape 3 : écrire le test qui échoue**

`api/tests/test_db.py` :

```python
from esquisse.db import connection


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
```

- [ ] **Étape 4 : lancer le test et vérifier qu'il échoue**

Lancer : `cd api && uv run pytest tests/test_db.py -v`
Attendu : ÉCHEC, `ModuleNotFoundError: No module named 'esquisse.db'`

- [ ] **Étape 5 : écrire la configuration**

`api/esquisse/config.py` :

```python
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ancré sur l'emplacement du module : le `.env` documenté vit à la racine du
# dépôt, alors que les commandes se lancent depuis `api/`. Un chemin relatif
# viserait `api/.env` et ne trouverait jamais le fichier.
_RACINE_DEPOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_RACINE_DEPOT / ".env", extra="ignore")

    supabase_db_host: str = "localhost"
    supabase_db_port: int = 5433
    supabase_db_user: str = "esquisse"
    supabase_db_password: str = "esquisse"
    supabase_db_name: str = "esquisse_test"

    session_ttl_hours: int = 24 * 14
    # pydantic-settings dérive le nom de la variable d'environnement du nom du
    # champ. L'alias garde `ESQUISSE_FAKE_LLM`, documenté au §11 de la spec,
    # sans imposer ce préfixe au nom Python.
    fake_llm: bool = Field(default=False, validation_alias="ESQUISSE_FAKE_LLM")

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.supabase_db_user}:{self.supabase_db_password}"
            f"@{self.supabase_db_host}:{self.supabase_db_port}/{self.supabase_db_name}"
        )


@lru_cache
def settings() -> Settings:
    return Settings()
```

- [ ] **Étape 6 : écrire le pool**

`api/esquisse/db.py` :

```python
from contextlib import asynccontextmanager
from functools import lru_cache

from psycopg_pool import AsyncConnectionPool

from esquisse.config import settings


@lru_cache
def pool() -> AsyncConnectionPool:
    """Le pooler Supabase est déjà en mode transaction : le pool local
    reste petit, il sert à éviter le coût d'établissement TLS, pas à
    multiplexer. Ouvrir trop de connexions ici ne gagne rien et
    consomme le quota du pooler."""
    return AsyncConnectionPool(
        conninfo=settings().dsn,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True},
    )


_opened = False


@asynccontextmanager
async def connection():
    """Ouvre le pool au premier usage. On ne s'appuie pas sur `pool.closed`,
    dont la valeur avant la première ouverture prête à confusion : un drapeau
    explicite est plus court à lire et ne dépend pas de la version."""
    global _opened
    p = pool()
    if not _opened:
        # `wait=True` : sans lui, `open()` rend la main avant la fin du
        # remplissage initial et entre en course avec la demande de connexion
        # juste en dessous — mesuré à plus d'un blocage sur deux.
        await p.open(wait=True)
        _opened = True
    async with p.connection() as conn:
        yield conn
```

- [ ] **Étape 7 : écrire conftest**

`api/tests/conftest.py` :

```python
import os

# Les tests parlent à la base jetable de docker-compose, jamais à la production.
os.environ.setdefault("SUPABASE_DB_HOST", "localhost")
os.environ.setdefault("SUPABASE_DB_PORT", "5433")
os.environ.setdefault("SUPABASE_DB_USER", "esquisse")
os.environ.setdefault("SUPABASE_DB_PASSWORD", "esquisse")
os.environ.setdefault("SUPABASE_DB_NAME", "esquisse_test")
```

- [ ] **Étape 8 : lancer les tests et vérifier qu'ils passent**

Lancer : `cd api && uv run pytest tests/test_db.py -v`
Attendu : SUCCÈS, deux tests

- [ ] **Étape 9 : prouver que les tests ne peuvent pas atteindre la base réelle**

Le `.env` de la racine contient les identifiants de production, et `env_file`
pointe désormais dessus. La seule chose qui protège la suite de tests est que
les variables d'environnement l'emportent sur `env_file`. Cela se prouve, et la
preuve doit tenir seule : un test qui ne pose le conflit que d'un côté passe au
vert sans rien démontrer dès que le `.env` local n'existe pas — sur un clone
neuf ou en intégration continue.

`api/tests/test_config.py` :

```python
from esquisse.config import Settings


def test_env_file_is_read_when_no_env_var(tmp_path, monkeypatch):
    fichier = tmp_path / ".env"
    fichier.write_text("SUPABASE_DB_NAME=venu_du_fichier\n", encoding="utf-8")
    monkeypatch.delenv("SUPABASE_DB_NAME", raising=False)
    assert Settings(_env_file=fichier).supabase_db_name == "venu_du_fichier"


def test_env_var_beats_env_file(tmp_path, monkeypatch):
    """Les deux côtés du conflit sont posés par le test lui-même : sans cela,
    il passerait au vert en ne démontrant rien."""
    fichier = tmp_path / ".env"
    fichier.write_text("SUPABASE_DB_NAME=venu_du_fichier\n", encoding="utf-8")
    monkeypatch.setenv("SUPABASE_DB_NAME", "venu_de_l_environnement")
    assert Settings(_env_file=fichier).supabase_db_name == "venu_de_l_environnement"


def test_fake_llm_reads_its_documented_env_var(monkeypatch):
    """L'alias n'est pas le comportement par défaut : sans lui le champ lirait
    FAKE_LLM. Un nettoyage futur casserait le contrat en silence."""
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    assert Settings().fake_llm is True
```

Lancer : `cd api && uv run pytest tests/test_config.py -v`
Attendu : SUCCÈS, trois tests

- [ ] **Étape 10 : commiter**

```bash
git add api/esquisse/config.py api/esquisse/db.py api/tests/conftest.py api/tests/test_db.py api/tests/test_config.py api/pyproject.toml api/uv.lock docker-compose.yml
git commit -m "feat(api): configuration et pool de connexions asynchrone"
```

---

## Tâche 3 : migrations et tables des comptes

**Fichiers :**
- Créer : `api/alembic.ini`
- Créer : `api/migrations/env.py`
- Créer : `api/migrations/versions/0001_accounts.py`
- Créer : `api/esquisse/safety.py`
- Modifier : `api/tests/conftest.py`
- Test : `api/tests/test_migrations.py`

**Interfaces :**
- Consomme : `esquisse.config.settings`
- Produit : les tables `users` et `sessions` conformes au §2.1 de la spec. La fixture pytest `migrated_db` (portée session) applique les migrations avant tout test.

- [ ] **Étape 1 : ajouter les dépendances**

```bash
cd api
uv add "alembic>=1.14" "sqlalchemy>=2.0"
uv run alembic init -t async migrations
```

Note : SQLAlchemy n'est utilisé que par Alembic. L'application n'en dépend pas et n'écrit que du SQL.

- [ ] **Étape 2 : écrire le test qui échoue**

`api/tests/test_migrations.py` :

```python
from esquisse.db import connection


async def test_account_tables_exist(migrated_db):
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                select table_name from information_schema.tables
                where table_schema = 'public' order by table_name
            """)
            tables = {r[0] for r in await cur.fetchall()}
    assert {"users", "sessions"} <= tables


async def test_is_active_defaults_to_false(migrated_db):
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash) values (%s, %s) returning is_active",
                ("defaut@exemple.fr", "x"),
            )
            assert (await cur.fetchone())[0] is False
            await cur.execute("delete from users where email = %s", ("defaut@exemple.fr",))
```

- [ ] **Étape 3 : lancer le test et vérifier qu'il échoue**

Lancer : `cd api && uv run pytest tests/test_migrations.py -v`
Attendu : ÉCHEC, fixture `migrated_db` introuvable

- [ ] **Étape 4 : configurer Alembic sur un moteur synchrone**

Remplacer le contenu de `api/migrations/env.py` par :

`api/esquisse/safety.py` — le garde-fou, dans un module à part parce que
`env.py` n'est pas importable et qu'un garde-fou non testable n'en est pas un :

```python
import os
from urllib.parse import urlparse

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_OPT_IN = "ESQUISSE_ALLOW_REMOTE_MIGRATIONS"


class RemoteMigrationRefused(RuntimeError):
    """Levée quand une migration vise une base non locale sans accord explicite."""


def ensure_migration_target_allowed(dsn: str) -> None:
    """Refuse d'appliquer une migration ailleurs qu'en local sans consentement.

    `env.py` lit les réglages comme l'application. Lancé à la main depuis
    `api/`, sans les variables que `conftest.py` pose pour les tests, il
    retombe sur le `.env` de la racine — celui qui porte les identifiants de
    production. Une frappe de trop et `alembic upgrade head` migre la base
    réelle. Le refus par défaut rend ce geste volontaire."""
    host = urlparse(dsn).hostname or ""
    if host in _LOCAL_HOSTS:
        return
    if os.environ.get(_OPT_IN) == "1":
        return
    raise RemoteMigrationRefused(
        f"Cible de migration non locale : {host}. "
        f"Pour l'accepter, relancez avec {_OPT_IN}=1."
    )
```

`api/migrations/env.py` :

```python
from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from esquisse.config import settings
from esquisse.safety import ensure_migration_target_allowed


def run_migrations_online() -> None:
    """Moteur synchrone : les migrations ne sont pas un chemin chaud et
    le pilote asynchrone n'apporte rien ici. Le DDL passe sans problème
    par le pooler en mode transaction."""
    ensure_migration_target_allowed(settings().dsn)
    dsn = settings().dsn.replace("postgresql://", "postgresql+psycopg://")
    # NullPool : une seule connexion, le processus se termine juste après.
    # `poolclass=None` ne désactive rien, contrairement à ce que son nom suggère.
    engine = create_engine(dsn, poolclass=NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
```

Dans `api/alembic.ini`, laisser `sqlalchemy.url` vide : la chaîne vient de `settings()`.

- [ ] **Étape 5 : écrire la migration**

`api/migrations/versions/0001_accounts.py` :

```python
"""comptes et sessions

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.execute("create extension if not exists citext")
    op.execute("create extension if not exists pgcrypto")
    op.execute("""
        create table users (
            id            uuid primary key default gen_random_uuid(),
            email         citext not null unique,
            password_hash text not null,
            is_active     boolean not null default false,
            created_at    timestamptz not null default now(),
            last_login_at timestamptz
        )
    """)
    op.execute("""
        create table sessions (
            token_hash bytea primary key,
            user_id    uuid not null references users(id) on delete cascade,
            created_at timestamptz not null default now(),
            expires_at timestamptz not null,
            revoked_at timestamptz
        )
    """)
    op.execute("create index sessions_user_id_idx on sessions (user_id)")


def downgrade() -> None:
    """Les extensions ne sont volontairement pas désinstallées.

    `drop extension` sur une base gérée peut casser des objets sans rapport
    avec ce projet, et sur Supabase les extensions relèvent de la plateforme.
    Une migration inverse qui désinstalle une extension partagée est plus
    dangereuse que l'asymétrie qu'elle corrigerait. `create extension if not
    exists` rend de toute façon la remontée idempotente."""
    op.execute("drop table if exists sessions")
    op.execute("drop table if exists users")
```

- [ ] **Étape 6 : ajouter la fixture à conftest**

Ajouter à `api/tests/conftest.py` :

```python
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def migrated_db():
    """Applique les migrations sur la base jetable avant la suite de tests.
    Même chemin qu'en production : si une migration casse, les tests cassent."""
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
```

- [ ] **Étape 7 : tester le garde-fou**

`api/tests/test_safety.py` :

```python
import pytest

from esquisse.safety import RemoteMigrationRefused, ensure_migration_target_allowed

LOCAL = "postgresql://u:p@localhost:5433/esquisse_test"
DISTANT = "postgresql://u:p@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"


def test_local_target_is_allowed(monkeypatch):
    monkeypatch.delenv("ESQUISSE_ALLOW_REMOTE_MIGRATIONS", raising=False)
    ensure_migration_target_allowed(LOCAL)


def test_remote_target_is_refused_by_default(monkeypatch):
    """Sans ce refus, la commande d'installation du README migrerait la
    base de production."""
    monkeypatch.delenv("ESQUISSE_ALLOW_REMOTE_MIGRATIONS", raising=False)
    with pytest.raises(RemoteMigrationRefused) as erreur:
        ensure_migration_target_allowed(DISTANT)
    assert "pooler.supabase.com" in str(erreur.value)


def test_remote_target_is_allowed_when_opted_in(monkeypatch):
    monkeypatch.setenv("ESQUISSE_ALLOW_REMOTE_MIGRATIONS", "1")
    ensure_migration_target_allowed(DISTANT)
```

Lancer : `cd api && uv run pytest tests/test_safety.py -v`
Attendu : SUCCÈS, trois tests

- [ ] **Étape 8 : lancer les tests et vérifier qu'ils passent**

Lancer : `cd api && uv run pytest tests/test_migrations.py -v`
Attendu : SUCCÈS, deux tests

- [ ] **Étape 9 : commiter**

```bash
git add api/alembic.ini api/migrations api/esquisse/safety.py api/tests/conftest.py api/tests/test_migrations.py api/tests/test_safety.py api/pyproject.toml api/uv.lock
git commit -m "feat(api): migrations Alembic et tables des comptes"
```

---

## Tâche 4 : empreintes de mot de passe et jetons

**Fichiers :**
- Créer : `api/esquisse/security.py`
- Test : `api/tests/test_security.py`

**Interfaces :**
- Consomme : rien.
- Produit :
  - `hash_password(password: str) -> str`
  - `verify_password(password: str | None, stored_hash: str | None) -> bool`
  - `new_token() -> tuple[str, bytes]` — rend le jeton en clair et son empreinte SHA-256
  - `token_hash(token: str) -> bytes`

- [ ] **Étape 1 : ajouter la dépendance**

```bash
cd api && uv add "argon2-cffi>=23.1"
```

- [ ] **Étape 2 : écrire le test qui échoue**

`api/tests/test_security.py` :

```python
import time

from esquisse.security import hash_password, verify_password, new_token, token_hash


def test_hash_does_not_contain_password():
    e = hash_password("correct horse battery staple")
    assert "correct" not in e
    assert e.startswith("$argon2id$")


def test_verify_accepts_correct_password():
    e = hash_password("motdepasse")
    assert verify_password("motdepasse", e) is True


def test_verify_rejects_wrong_password():
    e = hash_password("motdepasse")
    assert verify_password("autrechose", e) is False


def test_same_password_hashes_differ():
    """Le sel rend chaque empreinte unique : deux comptes avec le même
    mot de passe n'ont pas la même ligne en base."""
    assert hash_password("identique") != hash_password("identique")


def test_verify_pays_the_same_cost_when_digest_is_absent():
    """Une garde qui rend False sans appeler argon2 répondrait en
    microsecondes pour un compte inconnu, contre des dizaines de
    millisecondes pour un mauvais mot de passe. L'écart révélerait quels
    comptes existent. Le rapport toléré est large : sans la correction, il
    est de plusieurs ordres de grandeur."""
    reference = hash_password("motdepasse")

    debut = time.perf_counter()
    verify_password("mauvais", reference)
    cout_reel = time.perf_counter() - debut

    debut = time.perf_counter()
    verify_password("mauvais", None)
    cout_absent = time.perf_counter() - debut

    assert cout_absent > cout_reel / 3


def test_verify_refuses_none_instead_of_crashing():
    """Un appelant qui normalise le temps de réponse sur « utilisateur
    inconnu » passe naturellement None comme empreinte. Ce module doit
    répondre « non », jamais lever : une exception ici devient une 500."""
    assert verify_password("motdepasse", None) is False
    assert verify_password(None, hash_password("motdepasse")) is False
    assert verify_password("", "") is False


def test_new_token_is_unpredictable_and_digest_stable():
    clair_a, h_a = new_token()
    clair_b, h_b = new_token()
    assert clair_a != clair_b
    assert len(clair_a) >= 43           # 32 octets en base64url
    assert h_a == token_hash(clair_a)
    assert len(h_a) == 32               # SHA-256
```

- [ ] **Étape 3 : lancer le test et vérifier qu'il échoue**

Lancer : `cd api && uv run pytest tests/test_security.py -v`
Attendu : ÉCHEC, `ModuleNotFoundError: No module named 'esquisse.security'`

- [ ] **Étape 4 : écrire l'implémentation**

`api/esquisse/security.py` :

```python
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_hasher = PasswordHasher()

# Empreinte factice, calculée une fois au chargement du module. Elle sert
# uniquement à payer le coût d'argon2 quand aucune empreinte réelle n'existe.
_DUMMY_HASH = _hasher.hash("empreinte factice pour egaliser le temps de reponse")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str | None, stored_hash: str | None) -> bool:
    """Rend toujours un booléen, jamais une exception.

    Le cas `None` n'est pas théorique : pour ne pas révéler quels comptes
    existent, un appelant vérifie même quand l'utilisateur est introuvable, et
    passe alors une empreinte absente. argon2 lèverait un `AttributeError`
    avant d'atteindre ses propres exceptions, qui remonterait en erreur serveur.

    Mais rendre `False` tout de suite ne suffit pas : le chemin « compte
    inconnu » répondrait en microsecondes là où « mauvais mot de passe » paie
    les dizaines de millisecondes d'argon2, et cet écart révélerait
    précisément ce qu'on cherche à cacher. On vérifie donc contre une
    empreinte factice pour payer le même coût."""
    if not password:
        return False
    target = stored_hash if stored_hash else _DUMMY_HASH
    try:
        valid = _hasher.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    # Une empreinte absente ne vaut jamais un succès, même dans le cas
    # improbable où le mot de passe correspondrait à l'empreinte factice.
    return valid and stored_hash is not None


def new_token() -> tuple[str, bytes]:
    """Rend le jeton en clair, à donner une seule fois au client, et son
    empreinte, seule chose écrite en base. Une fuite de la table sessions
    ne permet pas de se connecter."""
    plaintext = secrets.token_urlsafe(32)
    return plaintext, token_hash(plaintext)


def token_hash(token: str) -> bytes:
    """SHA-256 nu, sans sel ni étirement, volontairement : le jeton porte déjà
    256 bits d'entropie tirés du générateur du système, donc le ralentir
    n'apporte rien contre la force brute — alors qu'une empreinte
    déterministe permet de retrouver la session par égalité indexée. Le
    contraste avec argon2id sur les mots de passe est un choix, pas un oubli."""
    return hashlib.sha256(token.encode()).digest()
```

- [ ] **Étape 5 : lancer les tests et vérifier qu'ils passent**

Lancer : `cd api && uv run pytest tests/test_security.py -v`
Attendu : SUCCÈS, cinq tests

- [ ] **Étape 6 : commiter**

```bash
git add api/esquisse/security.py api/tests/test_security.py api/pyproject.toml api/uv.lock
git commit -m "feat(api): empreintes argon2id et jetons de session"
```

---

## Tâche 5 : inscription

**Fichiers :**
- Créer : `api/esquisse/auth/__init__.py`
- Créer : `api/esquisse/auth/repository.py`
- Créer : `api/esquisse/auth/routes.py`
- Modifier : `api/esquisse/app.py`
- Modifier : `api/tests/conftest.py`
- Test : `api/tests/test_register.py`

**Interfaces :**
- Consomme : `esquisse.db.connexion`, `esquisse.security.hash_password`
- Produit :
  - `esquisse.auth.repository.create_user(conn, email: str, password_digest: str) -> UUID | None` — rend `None` si l'adresse existe déjà
  - `esquisse.auth.repository.user_by_email(conn, email: str) -> dict | None`
  - `esquisse.auth.routes.router` — `APIRouter` monté sur `/auth`
  - la fixture pytest `client`

- [ ] **Étape 1 : écrire le test qui échoue**

`api/tests/test_register.py` :

```python
from esquisse.db import connection


async def test_register_creates_inactive_account(client, migrated_db):
    reponse = await client.post(
        "/auth/register",
        json={"email": "nouvelle@exemple.fr", "mot_de_passe": "motdepasse123"},
    )
    assert reponse.status_code == 201
    assert reponse.json()["compte_actif"] is False

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select is_active, password_hash from users where email = %s",
                ("nouvelle@exemple.fr",),
            )
            actif, stored_hash = await cur.fetchone()
    assert actif is False
    assert "motdepasse123" not in stored_hash


async def test_existing_email_responds_identically(client, migrated_db):
    """On ne révèle pas qui est inscrit : deux réponses identiques."""
    premiere = await client.post(
        "/auth/register", json={"email": "double@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    seconde = await client.post(
        "/auth/register", json={"email": "double@exemple.fr", "mot_de_passe": "autrechose456"}
    )
    assert premiere.status_code == seconde.status_code == 201
    assert premiere.json() == seconde.json()

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select count(*) from users where email = %s", ("double@exemple.fr",))
            assert (await cur.fetchone())[0] == 1


async def test_short_password_rejected(client, migrated_db):
    reponse = await client.post(
        "/auth/register", json={"email": "court@exemple.fr", "mot_de_passe": "abc"}
    )
    assert reponse.status_code == 422
```

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Lancer : `cd api && uv run pytest tests/test_register.py -v`
Attendu : ÉCHEC, fixture `client` introuvable

- [ ] **Étape 3 : ajouter la fixture client**

Ajouter à `api/tests/conftest.py` :

```python
# Les imports de `esquisse` viennent APRÈS les affectations ci-dessus. Aujourd'hui
# `settings()` est paresseux et mémoïsé, donc l'ordre ne change rien — mais il
# suffirait qu'un module appelle `settings()` à l'import pour que la configuration
# se fige sur le `.env` de production. On ne fait pas reposer sur la chance ce que
# l'ordre garantit.
import httpx
import pytest_asyncio
from esquisse.app import create_app


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

- [ ] **Étape 4 : écrire le dépôt**

`api/esquisse/auth/__init__.py` : fichier vide.

`api/esquisse/auth/repository.py` :

```python
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
```

- [ ] **Étape 5 : écrire la route**

`api/esquisse/auth/routes.py` :

```python
import anyio
from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field

from esquisse.auth import repository
from esquisse.db import connection
from esquisse.security import hash_password

router = APIRouter(prefix="/auth", tags=["comptes"])


class RegisterRequest(BaseModel):
    email: EmailStr
    # Le maximum n'est pas cosmétique : sans lui, un client peut envoyer un
    # mot de passe de plusieurs mégaoctets qu'argon2 mettrait très longtemps à
    # hacher. 128 caractères laissent place à n'importe quelle phrase de passe.
    mot_de_passe: str = Field(min_length=10, max_length=128)


class RegisterResponse(BaseModel):
    compte_actif: bool
    message: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(demande: RegisterRequest) -> RegisterResponse:
    # Hachage hors de la boucle d'événements et AVANT d'ouvrir la connexion :
    # argon2 coûte des dizaines de millisecondes, pendant lesquelles il
    # bloquerait tout le serveur et retiendrait une des cinq connexions du pool.
    digest = await anyio.to_thread.run_sync(hash_password, demande.mot_de_passe)
    async with connection() as conn:
        # La valeur de retour est volontairement ignorée, et ne doit jamais
        # être testée dans un chemin de réponse : c'est ce qui garantit qu'une
        # adresse déjà prise réponde exactement comme une inscription réussie.
        await repository.create_user(conn, demande.email, digest)
    return RegisterResponse(
        compte_actif=False,
        message="Compte créé. Il sera utilisable une fois activé.",
    )
```

- [ ] **Étape 6 : monter le routeur**

Dans `api/esquisse/app.py`, à l'intérieur de `create_app()`, avant `return app` :

```python
    from esquisse.auth.routes import router as auth_router
    app.include_router(auth_router)
```

- [ ] **Étape 7 : ajouter la dépendance de validation d'adresse**

```bash
cd api && uv add "pydantic[email]>=2.9" "anyio>=4"
```

`anyio` arrive déjà par FastAPI, mais `routes.py` l'importe directement :
une dépendance qu'on importe se déclare, sinon elle disparaît le jour où
la bibliothèque qui l'amenait change d'avis.

- [ ] **Étape 8 : lancer les tests et vérifier qu'ils passent**

Lancer : `cd api && uv run pytest tests/test_register.py -v`
Attendu : SUCCÈS, trois tests

- [ ] **Étape 9 : commiter**

```bash
git add api/esquisse/auth api/esquisse/app.py api/tests/conftest.py api/tests/test_register.py api/pyproject.toml api/uv.lock
git commit -m "feat(api): inscription, compte inactif par défaut"
```

---

## Tâche 6 : connection, session et refus d'un compte inactif

**Fichiers :**
- Modifier : `api/esquisse/auth/repository.py`
- Modifier : `api/esquisse/auth/routes.py`
- Test : `api/tests/test_login.py`

**Interfaces :**
- Consomme : `new_token`, `verify_password`, `user_by_email`
- Produit :
  - `repository.open_session(conn, user_id: UUID, token_digest: bytes, ttl_hours: int) -> None`
  - `repository.revoke_session(conn, token_digest: bytes) -> None`
  - `POST /auth/login` rendant `{"jeton": str}`
  - `POST /auth/logout`

- [ ] **Étape 1 : écrire le test qui échoue**

`api/tests/test_login.py` :

```python
import hashlib

from esquisse.db import connection


async def _register_and_activate(client, email: str, actif: bool) -> None:
    await client.post("/auth/register", json={"email": email, "mot_de_passe": "motdepasse123"})
    if actif:
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("update users set is_active = true where email = %s", (email,))


async def test_login_returns_token(client, migrated_db):
    await _register_and_activate(client, "actif@exemple.fr", actif=True)
    reponse = await client.post(
        "/auth/login", json={"email": "actif@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    assert reponse.status_code == 200
    assert len(reponse.json()["jeton"]) >= 43


async def test_inactive_account_rejected_with_explicit_code(client, migrated_db):
    """403 et non 401 : les identifiants sont bons, c'est l'accès qui n'est
    pas ouvert. L'interface doit pouvoir afficher le bon écran."""
    await _register_and_activate(client, "attente@exemple.fr", actif=False)
    reponse = await client.post(
        "/auth/login", json={"email": "attente@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    assert reponse.status_code == 403
    assert reponse.json()["detail"] == "compte_inactif"


async def test_wrong_password_rejected(client, migrated_db):
    await _register_and_activate(client, "mauvais@exemple.fr", actif=True)
    reponse = await client.post(
        "/auth/login", json={"email": "mauvais@exemple.fr", "mot_de_passe": "pasbonlemotdepasse"}
    )
    assert reponse.status_code == 401


async def test_unknown_account_rejected_without_leak(client, migrated_db):
    reponse = await client.post(
        "/auth/login", json={"email": "jamais@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    assert reponse.status_code == 401


async def test_logout_accepts_any_case_of_the_scheme(client, migrated_db):
    """Un 204 sans révocation serait pire qu'une erreur : l'utilisateur se
    croirait déconnecté alors que son jeton resterait valable."""
    await _register_and_activate(client, "casse@exemple.fr", actif=True)
    r = await client.post(
        "/auth/login", json={"email": "casse@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    jeton = r.json()["jeton"]
    assert (await client.post("/auth/logout", headers={"Authorization": f"bearer {jeton}"})).status_code == 204

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select revoked_at from sessions where token_hash = %s",
                (hashlib.sha256(jeton.encode()).digest(),),
            )
            assert (await cur.fetchone())[0] is not None


async def test_logout_without_header_is_harmless(client, migrated_db):
    assert (await client.post("/auth/logout")).status_code == 204
    assert (await client.post("/auth/logout", headers={"Authorization": "n importe quoi"})).status_code == 204


async def test_plaintext_token_not_stored(client, migrated_db):
    await _register_and_activate(client, "empreinte@exemple.fr", actif=True)
    reponse = await client.post(
        "/auth/login", json={"email": "empreinte@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    jeton = reponse.json()["jeton"]
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select count(*) from sessions where token_hash = %s", (jeton.encode(),))
            assert (await cur.fetchone())[0] == 0
```

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Lancer : `cd api && uv run pytest tests/test_login.py -v`
Attendu : ÉCHEC, 404 sur `/auth/login`

- [ ] **Étape 3 : compléter le dépôt**

Ajouter à `api/esquisse/auth/repository.py` :

```python
from datetime import datetime, timedelta, timezone


async def open_session(conn, user_id: UUID, token_digest: bytes, ttl_hours: int) -> None:
    expire = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
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
```

- [ ] **Étape 4 : écrire les routes**

Ajouter à `api/esquisse/auth/routes.py` :

```python
from fastapi import Header, HTTPException

from esquisse.config import settings
from esquisse.security import new_token, verify_password, token_hash


class LoginRequest(BaseModel):
    email: EmailStr
    mot_de_passe: str = Field(max_length=128)


class LoginResponse(BaseModel):
    jeton: str


@router.post("/login")
async def login(demande: LoginRequest) -> LoginResponse:
    async with connection() as conn:
        user = await repository.user_by_email(conn, demande.email)

    # Hors de la connexion et hors de la boucle d'événements, pour la même
    # raison qu'à l'inscription. `verify_password` rend False sur une empreinte
    # absente : on le fait donc tourner même quand l'utilisateur est
    # introuvable, de sorte que les deux cas coûtent le même temps et qu'on
    # ne révèle pas quels comptes existent.
    stored = user["password_hash"] if user else None
    valide = await anyio.to_thread.run_sync(
        verify_password, demande.mot_de_passe, stored
    )
    if not user or not valide:
        raise HTTPException(status_code=401, detail="identifiants_invalides")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="compte_inactif")

    plaintext, token_digest = new_token()
    async with connection() as conn:
        await repository.open_session(
            conn, user["id"], token_digest, settings().session_ttl_hours
        )
    return LoginResponse(jeton=plaintext)


def _jeton_du_header(authorization: str) -> str:
    """Le schéma est insensible à la casse d'après la norme HTTP. Comparer
    « Bearer » au caractère près ferait qu'un client envoyant « bearer »
    recevrait un 204 sans que sa session soit révoquée : il se croirait
    déconnecté alors que son jeton reste valable."""
    schema, _, valeur = authorization.partition(" ")
    return valeur.strip() if schema.lower() == "bearer" else ""


@router.post("/logout", status_code=204)
async def logout(authorization: str = Header(default="")) -> None:
    jeton = _jeton_du_header(authorization)
    if jeton:
        async with connection() as conn:
            await repository.revoke_session(conn, token_hash(jeton))
```

- [ ] **Étape 5 : lancer les tests et vérifier qu'ils passent**

Lancer : `cd api && uv run pytest tests/test_login.py -v`
Attendu : SUCCÈS, cinq tests

- [ ] **Étape 6 : commiter**

```bash
git add api/esquisse/auth api/tests/test_login.py
git commit -m "feat(api): connection, sessions et refus des comptes non activés"
```

---

## Tâche 7 : dépendance « utilisateur actif » et route /me

**Fichiers :**
- Créer : `api/esquisse/auth/dependencies.py`
- Modifier : `api/esquisse/auth/routes.py`
- Test : `api/tests/test_dependencies.py`

**Interfaces :**
- Consomme : `token_hash`, `connexion`
- Produit : `esquisse.auth.dependencies.active_user` — dépendance FastAPI rendant `dict` avec `id` et `email`. Toutes les routes des plans suivants en dépendent.

- [ ] **Étape 1 : écrire le test qui échoue**

`api/tests/test_dependencies.py` :

```python
from esquisse.db import connection


async def _token_for(client, email: str) -> str:
    await client.post("/auth/register", json={"email": email, "mot_de_passe": "motdepasse123"})
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("update users set is_active = true where email = %s", (email,))
    r = await client.post("/auth/login", json={"email": email, "mot_de_passe": "motdepasse123"})
    return r.json()["jeton"]


async def test_me_returns_account(client, migrated_db):
    jeton = await _token_for(client, "moi@exemple.fr")
    r = await client.get("/me", headers={"Authorization": f"Bearer {jeton}"})
    assert r.status_code == 200
    assert r.json()["email"] == "moi@exemple.fr"


async def test_missing_token_rejected(client, migrated_db):
    assert (await client.get("/me")).status_code == 401


async def test_unknown_token_rejected(client, migrated_db):
    r = await client.get("/me", headers={"Authorization": "Bearer nimportequoi"})
    assert r.status_code == 401


async def test_deactivation_takes_effect_immediately(client, migrated_db):
    """Le cœur du choix des jetons opaques : le drapeau est basculé à la
    main dans la base, et le jeton déjà émis cesse de valoir aussitôt.
    Un JWT resterait valable jusqu'à son expiration."""
    jeton = await _token_for(client, "coupe@exemple.fr")
    entetes = {"Authorization": f"Bearer {jeton}"}
    assert (await client.get("/me", headers=entetes)).status_code == 200

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("update users set is_active = false where email = %s", ("coupe@exemple.fr",))

    assert (await client.get("/me", headers=entetes)).status_code == 403


async def test_deconnexion_invalide_le_jeton(client, migrated_db):
    jeton = await _token_for(client, "sortie@exemple.fr")
    entetes = {"Authorization": f"Bearer {jeton}"}
    assert (await client.post("/auth/logout", headers=entetes)).status_code == 204
    assert (await client.get("/me", headers=entetes)).status_code == 401
```

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Lancer : `cd api && uv run pytest tests/test_dependencies.py -v`
Attendu : ÉCHEC, 404 sur `/me`

- [ ] **Étape 3 : écrire la dépendance**

`api/esquisse/auth/dependencies.py` :

```python
from fastapi import Header, HTTPException

from esquisse.db import connection
from esquisse.security import token_hash


async def active_user(authorization: str = Header(default="")) -> dict:
    """Une requête par appel, indexée sur la clé primaire de sessions.
    C'est le prix de la révocation instantanée, et il est négligeable
    aux volumes visés."""
    jeton = authorization.removeprefix("Bearer ").strip()
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
```

- [ ] **Étape 4 : ajouter la route /me**

Ajouter à `api/esquisse/auth/routes.py` :

```python
from fastapi import Depends

from esquisse.auth.dependencies import active_user

me_router = APIRouter(tags=["comptes"])


@me_router.get("/me")
async def me(utilisateur: dict = Depends(active_user)) -> dict:
    return {"email": utilisateur["email"], "compte_actif": True}
```

Dans `api/esquisse/app.py`, monter aussi ce routeur :

```python
    from esquisse.auth.routes import me_router
    app.include_router(me_router)
```

- [ ] **Étape 5 : lancer les tests et vérifier qu'ils passent**

Lancer : `cd api && uv run pytest tests/test_dependencies.py -v`
Attendu : SUCCÈS, cinq tests

- [ ] **Étape 6 : commiter**

```bash
git add api/esquisse/auth api/esquisse/app.py api/tests/test_dependencies.py
git commit -m "feat(api): dépendance utilisateur actif et route /me"
```

---

## Tâche 8 : tables des projets et cloisonnement vérifié

**Fichiers :**
- Créer : `api/migrations/versions/0002_projects.py`
- Créer : `api/esquisse/projects/__init__.py`
- Créer : `api/esquisse/projects/repository.py`
- Test : `api/tests/test_isolation.py`

**Interfaces :**
- Consomme : `connexion`
- Produit :
  - les tables `projects`, `facts`, `sections`, `exports`, `llm_usage` du §2.1 de la spec
  - `esquisse.projects.repository.project_for_user(conn, project_id: UUID, user_id: UUID) -> dict` — lève `ProjectNotFound`
  - `esquisse.projects.repository.ProjectNotFound`
  - `esquisse.projects.repository.create_project(conn, user_id, nom, documents, profil_cdc, profil_bp, thread_id, templates_version) -> UUID`

- [ ] **Étape 1 : écrire le test qui échoue**

`api/tests/test_isolation.py` :

```python
from pathlib import Path
from uuid import uuid4

import pytest

from esquisse.db import connection
from esquisse.projects.repository import (
    ProjectNotFound,
    create_project,
    project_for_user,
)


async def _make_user(email: str):
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) values (%s, 'x', true) returning id",
                (email,),
            )
            return (await cur.fetchone())[0]


async def test_owner_reads_own_project(migrated_db):
    uid = await _make_user(f"prop-{uuid4()}@exemple.fr")
    async with connection() as conn:
        pid = await create_project(conn, uid, "CoachDom", "both", "consultation", "banque",
                                 f"thread-{uuid4()}", "0.1")
        projet = await project_for_user(conn, pid, uid)
    assert projet["nom"] == "CoachDom"


async def test_other_user_cannot_find_it(migrated_db):
    """Introuvable, pas interdit : répondre 403 révélerait que le projet existe."""
    proprietaire = await _make_user(f"a-{uuid4()}@exemple.fr")
    intrus = await _make_user(f"b-{uuid4()}@exemple.fr")
    async with connection() as conn:
        pid = await create_project(conn, proprietaire, "Privé", "cdc", "cadrage", None,
                                 f"thread-{uuid4()}", "0.1")
        with pytest.raises(ProjectNotFound):
            await project_for_user(conn, pid, intrus)


async def test_missing_project_raises_same_error(migrated_db):
    uid = await _make_user(f"c-{uuid4()}@exemple.fr")
    async with connection() as conn:
        with pytest.raises(ProjectNotFound):
            await project_for_user(conn, uuid4(), uid)


def test_no_projects_query_outside_repository():
    """Garde-fou structurel : le cloisonnement ne vaut que si personne ne
    contourne le dépôt. Ce test casse dès qu'une route écrit son propre SQL."""
    racine = Path(__file__).resolve().parents[1] / "esquisse"
    autorise = racine / "projects" / "repository.py"
    coupables = [
        f for f in racine.rglob("*.py")
        if f != autorise and "from projects" in f.read_text(encoding="utf-8").lower()
    ]
    assert coupables == [], f"SQL sur projects hors du dépôt : {coupables}"
```

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Lancer : `cd api && uv run pytest tests/test_isolation.py -v`
Attendu : ÉCHEC, `ModuleNotFoundError: No module named 'esquisse.projects'`

- [ ] **Étape 3 : écrire la migration**

`api/migrations/versions/0002_projects.py` :

```python
"""projets, faits, sections, exports, usage des modèles

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute("""
        create table projects (
            id                uuid primary key default gen_random_uuid(),
            user_id           uuid not null references users(id) on delete cascade,
            nom               text not null,
            documents         text not null,
            profil_cdc        text,
            profil_bp         text,
            thread_id         text not null unique,
            run_status        text not null default 'idle',
            templates_version text not null,
            created_at        timestamptz not null default now(),
            updated_at        timestamptz not null default now()
        )
    """)
    op.execute("create index projects_user_idx on projects (user_id, updated_at desc)")
    op.execute("""
        create table facts (
            project_id uuid not null references projects(id) on delete cascade,
            fact_id    text not null,
            valeur     jsonb,
            source     text not null,
            confiance  real,
            updated_at timestamptz not null default now(),
            primary key (project_id, fact_id)
        )
    """)
    op.execute("""
        create table sections (
            project_id uuid not null references projects(id) on delete cascade,
            section_id text not null,
            document   text not null,
            ordre      int not null,
            statut     text not null default 'pending',
            contenu    jsonb,
            note       int,
            revisions  int not null default 0,
            valide_par text,
            valide_le  timestamptz,
            primary key (project_id, section_id)
        )
    """)
    op.execute("create index sections_ordre_idx on sections (project_id, ordre)")
    op.execute("""
        create table exports (
            id           uuid primary key default gen_random_uuid(),
            project_id   uuid not null references projects(id) on delete cascade,
            document     text not null,
            format       text not null,
            storage_path text not null,
            brouillon    boolean not null default false,
            created_at   timestamptz not null default now()
        )
    """)
    op.execute("create index exports_projet_idx on exports (project_id)")
    op.execute("""
        create table llm_usage (
            id          bigserial primary key,
            fournisseur text not null,
            modele      text not null,
            route       text not null,
            project_id  uuid references projects(id) on delete set null,
            requetes    int not null default 1,
            tokens      int not null default 0,
            issue       text not null,
            at          timestamptz not null default now()
        )
    """)
    op.execute("create index llm_usage_fournisseur_idx on llm_usage (fournisseur, at desc)")


def downgrade() -> None:
    for table in ("llm_usage", "exports", "sections", "facts", "projects"):
        op.execute(f"drop table if exists {table}")
```

- [ ] **Étape 4 : écrire le dépôt**

`api/esquisse/projects/__init__.py` : fichier vide.

`api/esquisse/projects/repository.py` :

```python
from uuid import UUID


class ProjectNotFound(Exception):
    """Levée aussi bien quand le projet n'existe pas que quand il
    appartient à quelqu'un d'autre. Les deux cas se répondent pareil."""


async def create_project(
    conn,
    user_id: UUID,
    nom: str,
    documents: str,
    profil_cdc: str | None,
    profil_bp: str | None,
    thread_id: str,
    templates_version: str,
) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into projects
                (user_id, nom, documents, profil_cdc, profil_bp, thread_id, templates_version)
            values (%s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (user_id, nom, documents, profil_cdc, profil_bp, thread_id, templates_version),
        )
        return (await cur.fetchone())[0]


async def project_for_user(conn, project_id: UUID, user_id: UUID) -> dict:
    """Seul accès en lecture à la table projects dans toute l'application.
    Le filtre sur le propriétaire est dans la requête, pas dans l'appelant :
    on ne peut pas l'oublier."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select id, user_id, nom, documents, profil_cdc, profil_bp,
                   thread_id, run_status, templates_version
            from projects where id = %s and user_id = %s
            """,
            (project_id, user_id),
        )
        ligne = await cur.fetchone()
    if not ligne:
        raise ProjectNotFound
    champs = ("id", "user_id", "nom", "documents", "profil_cdc", "profil_bp",
              "thread_id", "run_status", "templates_version")
    return dict(zip(champs, ligne))
```

- [ ] **Étape 5 : lancer les tests et vérifier qu'ils passent**

Lancer : `cd api && uv run pytest tests/test_isolation.py -v`
Attendu : SUCCÈS, quatre tests

- [ ] **Étape 6 : lancer toute la suite**

Lancer : `cd api && uv run pytest -v`
Attendu : SUCCÈS, tous les tests des tâches 1 à 8

- [ ] **Étape 7 : commiter**

```bash
git add api/migrations api/esquisse/projects api/tests/test_isolation.py
git commit -m "feat(api): tables des projets et cloisonnement par le dépôt"
```

---

## Tâche 9 : limitation de débit sur les routes de compte

**Fichiers :**
- Créer : `api/esquisse/rate_limit.py`
- Modifier : `api/esquisse/auth/routes.py`
- Test : `api/tests/test_rate_limit.py`

**Interfaces :**
- Consomme : rien.
- Produit : `esquisse.rate_limit.SlidingWindowCounter` avec `allow(cle: str) -> bool` et `reset() -> None`.

- [ ] **Étape 1 : écrire le test qui échoue**

`api/tests/test_rate_limit.py` :

```python
import pytest
from esquisse.rate_limit import SlidingWindowCounter


def test_autorise_jusqua_la_limite():
    compteur = SlidingWindowCounter(maximum=3, window_seconds=900)
    assert [compteur.allow("1.2.3.4") for _ in range(4)] == [True, True, True, False]


def test_keys_are_independent():
    compteur = SlidingWindowCounter(maximum=1, window_seconds=900)
    assert compteur.allow("1.2.3.4") is True
    assert compteur.allow("5.6.7.8") is True
    assert compteur.allow("1.2.3.4") is False


def test_window_slides():
    clock_value = [1000.0]
    compteur = SlidingWindowCounter(maximum=1, window_seconds=10, clock=lambda: clock_value[0])
    assert compteur.allow("ip") is True
    assert compteur.allow("ip") is False
    clock_value[0] += 11
    assert compteur.allow("ip") is True


async def test_login_is_rate_limited(client, migrated_db):
    for _ in range(10):
        await client.post("/auth/login", json={"email": "x@exemple.fr", "mot_de_passe": "motdepasse123"})
    reponse = await client.post(
        "/auth/login", json={"email": "x@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    assert reponse.status_code == 429
```

- [ ] **Étape 2 : lancer le test et vérifier qu'il échoue**

Lancer : `cd api && uv run pytest tests/test_rate_limit.py -v`
Attendu : ÉCHEC, `ModuleNotFoundError: No module named 'esquisse.rate_limit'`

- [ ] **Étape 3 : écrire le compteur**

`api/esquisse/rate_limit.py` :

```python
import time
from collections import defaultdict, deque
from collections.abc import Callable


class SlidingWindowCounter:
    """Fenêtre glissante en mémoire du processus.

    Correct tant qu'il n'y a qu'une instance, ce qui est le cas sur
    l'hébergement gratuit. Passer à plusieurs instances rendrait ce
    compteur inopérant : il faudrait le déplacer en base.
    """

    def __init__(self, maximum: int, window_seconds: int,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.maximum = maximum
        self.window = window_seconds
        self.clock = clock
        self._passages: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, cle: str) -> bool:
        maintenant = self.clock()
        passages = self._passages[cle]
        while passages and maintenant - passages[0] > self.window:
            passages.popleft()
        if len(passages) >= self.maximum:
            return False
        passages.append(maintenant)
        return True

    def reset(self) -> None:
        self._passages.clear()
```

- [ ] **Étape 4 : brancher sur les routes de compte**

Ajouter à `api/esquisse/auth/routes.py` :

```python
from fastapi import Request

from esquisse.rate_limit import SlidingWindowCounter

_account_limiter = SlidingWindowCounter(maximum=10, window_seconds=900)


def _check_rate_limit(requete: Request) -> None:
    ip = requete.client.host if requete.client else "inconnue"
    if not _account_limiter.allow(ip):
        raise HTTPException(status_code=429, detail="trop_de_tentatives")
```

Ajouter `requete: Request` en premier paramètre de `register` et de `login`, et appeler `_check_rate_limit(requete)` en première ligne de chacune.

- [ ] **Étape 5 : isoler les tests les uns des autres**

Ajouter à `api/tests/conftest.py` :

```python
@pytest.fixture(autouse=True)
def _fresh_rate_limit():
    """Le compteur vit dans le processus : sans remise à zéro, un test
    qui consomme la limite fait échouer le suivant."""
    from esquisse.auth import routes
    routes._account_limiter.reset()
    yield
```

- [ ] **Étape 6 : lancer les tests et vérifier qu'ils passent**

Lancer : `cd api && uv run pytest tests/test_rate_limit.py -v`
Attendu : SUCCÈS, quatre tests

- [ ] **Étape 7 : lancer toute la suite**

Lancer : `cd api && uv run pytest -v`
Attendu : SUCCÈS

- [ ] **Étape 8 : commiter**

```bash
git add api/esquisse/rate_limit.py api/esquisse/auth/routes.py api/tests/conftest.py api/tests/test_rate_limit.py
git commit -m "feat(api): limitation de débit sur inscription et connexion"
```

---

## Tâche 10 : conteneur et intégration continue

**Fichiers :**
- Créer : `api/Dockerfile`
- Créer : `api/.dockerignore`
- Créer : `render.yaml` (racine)
- Créer : `.github/workflows/ci.yml`
- Modifier : `docker-compose.yml`

**Interfaces :**
- Consomme : tout ce qui précède.
- Produit : une image qui démarre, et une intégration continue qui refuse un verrou désynchronisé.

- [ ] **Étape 1 : écrire le Dockerfile**

`api/Dockerfile` :

```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Le manifeste et le verrou d'abord : tant qu'ils ne bougent pas, la couche
# des dépendances reste en cache et la construction ne coûte presque rien.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "-c", "alembic upgrade head && uvicorn esquisse.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

`api/.dockerignore` :

```
.venv
__pycache__
tests
.pytest_cache
```

- [ ] **Étape 2 : vérifier que l'image se construit et démarre**

```bash
cd api && docker build -t esquisse-api .
```

Attendu : construction réussie.

- [ ] **Étape 3 : décrire les deux services de production**

`render.yaml` à la racine :

```yaml
services:
  - type: web
    name: esquisse-api
    runtime: docker
    dockerfilePath: ./api/Dockerfile
    dockerContext: ./api
    plan: free
    healthCheckPath: /health
    envVars:
      - key: SUPABASE_DB_HOST
        sync: false
      - key: SUPABASE_DB_PORT
        sync: false
      - key: SUPABASE_DB_USER
        sync: false
      - key: SUPABASE_DB_PASSWORD
        sync: false
      - key: SUPABASE_DB_NAME
        sync: false

  # Image officielle épinglée. Un service déployé depuis une image
  # pré-construite ne se redéploie pas tout seul : c'est voulu ici.
  # Il dort pendant toute la rédaction et n'est réveillé qu'à l'export,
  # parce que les 750 heures d'instance mensuelles sont partagées
  # entre tous les services de l'espace de travail.
  - type: web
    name: esquisse-gotenberg
    runtime: image
    image:
      url: docker.io/gotenberg/gotenberg:8
    plan: free
```

- [ ] **Étape 4 : écrire l'intégration continue**

`.github/workflows/ci.yml` :

```yaml
name: ci

on: [push, pull_request]

jobs:
  tests:
    runs-on: ubuntu-latest
    services:
      db:
        image: postgres:17
        env:
          POSTGRES_PASSWORD: esquisse
          POSTGRES_USER: esquisse
          POSTGRES_DB: esquisse_test
        ports: ["5433:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - name: Installer les dépendances
        working-directory: api
        # --frozen : le verrou fait foi. Une dépendance qui dérive fait
        # échouer la construction au lieu d'être résolue autrement.
        run: uv sync --frozen
      - name: Tests
        working-directory: api
        env:
          SUPABASE_DB_HOST: localhost
          SUPABASE_DB_PORT: "5433"
          SUPABASE_DB_USER: esquisse
          SUPABASE_DB_PASSWORD: esquisse
          SUPABASE_DB_NAME: esquisse_test
        run: uv run pytest -v
```

- [ ] **Étape 5 : vérifier que le verrou est à jour**

Lancer : `cd api && uv sync --frozen`
Attendu : SUCCÈS. Si la commande échoue, lancer `uv lock` puis commiter le verrou.

- [ ] **Étape 6 : commiter**

```bash
git add api/Dockerfile api/.dockerignore render.yaml .github/workflows/ci.yml docker-compose.yml
git commit -m "build: image du backend, description des services Render, intégration continue"
```

---

## Tâche 11 : README du dépôt

**Fichiers :**
- Créer : `README.md` (racine)
- Créer : `.env.example` (racine)

**Interfaces :**
- Consomme : tout ce qui précède. Les commandes documentées doivent être celles qui marchent réellement.
- Produit : rien que le code consomme.

- [ ] **Étape 1 : écrire le README**

Créer `README.md` à la racine du dépôt. Contenu (les titres ci-dessous sont
ceux du README lui-même, pas des titres de ce plan) :

````markdown
# Esquisse

Génère un cahier des charges et un business plan à partir d'une idée de projet,
en posant des questions ciblées plutôt qu'en demandant de remplir un formulaire.

### En deux mots

Un porteur de projet décrit son idée en quelques phrases. L'agent en extrait ce
qu'il peut, demande le reste, rédige les sections une à une, se relit, et ne
dérange l'utilisateur que lorsque sa relecture n'est pas satisfaite. À la fin,
quatre fichiers : le cahier des charges et le business plan, en Word et en PDF.

### Documents de référence

| Document | Ce qu'il contient |
|---|---|
| [docs/mockup.html](docs/mockup.html) | Prototype cliquable, workflow en 18 étapes, stack technique. À ouvrir dans un navigateur. |
| [docs/analyse-cdc-bp.md](docs/analyse-cdc-bp.md) | Ce que doivent contenir les deux documents, d'après les normes et d'après de vrais documents. Sources en fin de page. |
| [docs/templates/](docs/templates/) | 30 sections et 74 faits, en YAML. Le cœur de valeur du produit. |
| [docs/spec-implementation.md](docs/spec-implementation.md) | Spécification technique. |
| [docs/plans/](docs/plans/) | Feuille de route et plans d'implémentation. |

### Démarrer

Prérequis : Python 3.12, [uv](https://docs.astral.sh/uv/), Docker.

```bash
docker compose up -d db          # base de développement et de test
cd api && uv sync                # dépendances
uv run alembic upgrade head      # migrations
uv run uvicorn esquisse.app:app --reload --port 8000
```

`curl localhost:8000/health` doit répondre `{"statut":"ok"}`.

### Tests

```bash
cd api && uv run pytest -v
```

Les tests utilisent la base jetable de `docker-compose.yml`, jamais la base
distante. Aucun test ne joint un fournisseur de modèle.

### Configuration

Copier `.env.example` en `.env` à la racine et le remplir. Le fichier `.env`
n'est jamais versionné.

### Comptes

L'inscription est ouverte, mais un compte créé n'est pas utilisable. Le drapeau
`is_active` se bascule à la main dans la base :

```sql
update users set is_active = true where email = 'quelquun@exemple.fr';
```

C'est volontaire : la génération repose sur des paliers gratuits dont les quotas
sont journaliers et partagés. Une inscription libre les épuiserait en une matinée.

### Conventions

Les identifiants du code — fonctions, classes, modules, fichiers — sont en
anglais. Les commentaires, les docstrings et la documentation sont en français.

Dépendances gérées par `uv`, jamais `pip`. `pyproject.toml` déclare, `uv.lock`
verrouille, les deux sont versionnés. Toute commande passe par `uv run`.
````

- [ ] **Étape 2 : écrire le fichier d'exemple de configuration**

Créer `.env.example` à la racine, sans aucune valeur réelle :

```
# Base PostgreSQL — pooler Supabase en mode transaction
SUPABASE_DB_HOST=aws-0-eu-central-1.pooler.supabase.com
SUPABASE_DB_PORT=6543
SUPABASE_DB_USER=
SUPABASE_DB_PASSWORD=
SUPABASE_DB_NAME=postgres

# Stockage des exports
SUPABASE_URL=
SUPABASE_SERVICE_KEY=

# Fournisseurs de modèles, paliers gratuits
GEMINI_API_KEY=
MISTRAL_AI_API_KEY=
OPENROUTER_API_KEY=
NVIDIA_API_KEY=
GROQ_CLOUD_API_KEY=

# Suivi
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=esquisse

# Rendu des PDF
GOTENBERG_URL=

# Sessions et développement
SESSION_TTL_HOURS=336
ESQUISSE_FAKE_LLM=false
```

- [ ] **Étape 3 : vérifier que les commandes du README fonctionnent**

Exécuter, depuis un dépôt propre, chacune des commandes du bloc « Démarrer »
puis celle des « Tests ».
Attendu : chaque commande réussit, `/health` répond `{"statut":"ok"}`, la suite
de tests passe entièrement. Corriger le README si une commande diverge.

- [ ] **Étape 4 : vérifier qu'aucun secret n'a filé**

Lancer : `git check-ignore -q .env && echo ignoré`
Attendu : `ignoré`.

Lancer ensuite : `grep -E "=.+" .env.example`
Attendu : seules les lignes `SUPABASE_DB_HOST`, `SUPABASE_DB_PORT`,
`SUPABASE_DB_NAME`, `LANGSMITH_PROJECT`, `SESSION_TTL_HOURS` et
`ESQUISSE_FAKE_LLM` ont une valeur, et aucune n'est un secret.

- [ ] **Étape 5 : commiter**

```bash
git add README.md .env.example
git commit -m "docs: README du dépôt et exemple de configuration"
```

---

## Ce que ce plan ne fait pas

Aucune route de projet exposée en HTTP : la tâche 8 crée les tables et le dépôt, pas les routes. Elles arrivent au plan 4, quand l'agent qu'elles pilotent existe.

Aucune politique de sécurité au niveau des lignes. Le cloisonnement est porté par le dépôt et vérifié par un test structurel. Les politiques peuvent venir en seconde barrière, en posant l'identifiant en `SET LOCAL` — la tâche 2 a déjà prouvé que le mécanisme fonctionne à travers le pooler.

Aucune réinitialisation de mot de passe. Hors périmètre de la première version, comme l'activation : cela se fait à la main dans la base.
