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
