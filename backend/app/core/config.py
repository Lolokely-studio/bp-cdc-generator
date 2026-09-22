from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Le fichier vit dans backend/app/core/ : deux niveaux au-dessus se trouve la
# racine de backend/, où README et .env.example placent le `.env`. On ancre le
# chemin sur l'emplacement du module plutôt que sur le répertoire courant, car
# toutes les commandes se lancent depuis `backend/` et un chemin relatif
# (".env") y pointerait sur `backend/.env`, qui n'existe pas. En conteneur, ce
# chemin ne trouvera aucun fichier : sans effet, les réglages y viennent de
# l'environnement de l'hébergeur.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Réglages de l'application, lus depuis l'environnement (ou `.env`
    à la racine de backend/ en développement)."""

    model_config = SettingsConfigDict(env_file=_BACKEND_ROOT / ".env", extra="ignore")

    supabase_db_host: str = "localhost"
    supabase_db_port: int = 5433
    supabase_db_user: str = "esquisse"
    supabase_db_password: str = "esquisse"
    supabase_db_name: str = "esquisse_test"

    session_ttl_hours: int = 24 * 14
    # Nom d'attribut conforme à l'interface publiée (§ tâche 2 : `fake_llm: bool`),
    # mais lié à la variable d'environnement `ESQUISSE_FAKE_LLM` documentée au
    # §11 de la spec : l'alias préserve ce contrat externe sans imposer son
    # préfixe au nom Python.
    fake_llm: bool = Field(default=False, validation_alias="ESQUISSE_FAKE_LLM")

    # Paliers gratuits des cinq fournisseurs de modèles. Le nom d'attribut
    # donne la variable d'environnement en majuscules : `gemini_api_key` lit
    # `GEMINI_API_KEY`, conformément au §11 de la spec. Valeur vide par
    # défaut, ce qui vaut « non configuré » et fait sauter le fournisseur.
    gemini_api_key: str = ""
    mistral_ai_api_key: str = ""
    openrouter_api_key: str = ""
    nvidia_api_key: str = ""
    groq_cloud_api_key: str = ""

    # Gotenberg, réveillé seulement à l'export (§9.4). Service web PUBLIC —
    # les services privés sont payants chez Render — donc protégé par
    # l'authentification de base qu'il sait faire depuis sa version 8.
    # URL vide : aucun Gotenberg configuré, et l'export passe directement au
    # repli HTML.
    gotenberg_url: str = ""
    gotenberg_username: str = ""
    gotenberg_password: str = ""
    # Le premier appel paie le réveil du service, environ une minute.
    gotenberg_timeout_seconds: float = 120.0

    @property
    def dsn(self) -> str:
        """DSN PostgreSQL construit à partir des variables SUPABASE_DB_*."""
        return (
            f"postgresql://{self.supabase_db_user}:{self.supabase_db_password}"
            f"@{self.supabase_db_host}:{self.supabase_db_port}/{self.supabase_db_name}"
        )


@lru_cache
def settings() -> Settings:
    """Instance mémoïsée des réglages : une seule lecture de l'environnement
    par processus."""
    return Settings()
