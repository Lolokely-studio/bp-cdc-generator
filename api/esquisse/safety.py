import os
from urllib.parse import urlparse

_HOTES_LOCAUX = {"localhost", "127.0.0.1", "::1"}
_AUTORISATION = "ESQUISSE_ALLOW_REMOTE_MIGRATIONS"


class RemoteMigrationRefused(RuntimeError):
    """Levée quand une migration vise une base non locale sans accord explicite."""


def ensure_migration_target_allowed(dsn: str) -> None:
    """Refuse d'appliquer une migration ailleurs qu'en local sans consentement.

    `env.py` lit les réglages comme l'application. Lancé à la main depuis
    `api/`, sans les variables que `conftest.py` pose pour les tests, il
    retombe sur le `.env` de la racine — celui qui porte les identifiants de
    production. Une frappe de trop et `alembic upgrade head` migre la base
    réelle. Le refus par défaut rend ce geste volontaire."""
    hote = urlparse(dsn).hostname or ""
    if hote in _HOTES_LOCAUX:
        return
    if os.environ.get(_AUTORISATION) == "1":
        return
    raise RemoteMigrationRefused(
        f"Cible de migration non locale : {hote}. "
        f"Pour l'accepter, relancez avec {_AUTORISATION}=1."
    )
