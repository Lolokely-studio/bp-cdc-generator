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
