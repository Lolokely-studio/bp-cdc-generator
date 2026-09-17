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
