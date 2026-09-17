from alembic import context
from sqlalchemy import create_engine

from esquisse.config import settings


def run_migrations_online() -> None:
    """Moteur synchrone : les migrations ne sont pas un chemin chaud et
    le pilote asynchrone n'apporte rien ici. Le DDL passe sans problème
    par le pooler en mode transaction."""
    dsn = settings().dsn.replace("postgresql://", "postgresql+psycopg://")
    engine = create_engine(dsn, poolclass=None)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
