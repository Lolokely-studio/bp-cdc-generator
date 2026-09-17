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
