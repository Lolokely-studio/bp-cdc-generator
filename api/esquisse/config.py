from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Reglages(BaseSettings):
    """Réglages de l'application, lus depuis l'environnement (ou `.env`
    à la racine du dépôt en développement)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_db_host: str = "localhost"
    supabase_db_port: int = 5433
    supabase_db_user: str = "esquisse"
    supabase_db_password: str = "esquisse"
    supabase_db_name: str = "esquisse_test"

    session_ttl_heures: int = 24 * 14
    # Nom d'attribut conforme à l'interface publiée (§ tâche 2 : `fake_llm: bool`),
    # mais lié à la variable d'environnement `ESQUISSE_FAKE_LLM` documentée au
    # §11 de la spec : l'alias préserve ce contrat externe sans imposer son
    # préfixe au nom Python.
    fake_llm: bool = Field(default=False, validation_alias="ESQUISSE_FAKE_LLM")

    @property
    def dsn(self) -> str:
        """DSN PostgreSQL construit à partir des variables SUPABASE_DB_*."""
        return (
            f"postgresql://{self.supabase_db_user}:{self.supabase_db_password}"
            f"@{self.supabase_db_host}:{self.supabase_db_port}/{self.supabase_db_name}"
        )


@lru_cache
def settings() -> Reglages:
    """Instance mémoïsée des réglages : une seule lecture de l'environnement
    par processus."""
    return Reglages()
