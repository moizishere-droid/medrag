"""
Typed application settings, loaded from environment variables / .env file.

Note: this file lives in backend/config/ (outside the medrag src package),
so it's imported relative to the backend/ folder, e.g. when running scripts
from backend/scripts/:
    from config.settings import settings
    settings.openai_api_key
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
from pathlib import Path

# Resolve .env relative to this file's location (backend/config/settings.py),
# not the current working directory — so it works whether you run scripts
# from the project root, from backend/, or from backend/scripts/.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    # --- OpenAI ---
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")

    # --- PubMed E-utilities ---
    pubmed_email: str = Field(..., alias="PUBMED_EMAIL")

    # --- Qdrant (not required until Phase 9) ---
    qdrant_url: Optional[str] = Field(default=None, alias="QDRANT_URL")

    # --- Neo4j (not required until Phase 14) ---
    neo4j_uri: Optional[str] = Field(default=None, alias="NEO4J_URI")
    neo4j_user: Optional[str] = Field(default=None, alias="NEO4J_USER")
    neo4j_password: Optional[str] = Field(default=None, alias="NEO4J_PASSWORD")

    # --- PostgreSQL (not required until Phase 17) ---
    postgres_host: Optional[str] = Field(default=None, alias="POSTGRES_HOST")
    postgres_port: Optional[int] = Field(default=None, alias="POSTGRES_PORT")
    postgres_db: Optional[str] = Field(default=None, alias="POSTGRES_DB")
    postgres_user: Optional[str] = Field(default=None, alias="POSTGRES_USER")
    postgres_password: Optional[str] = Field(default=None, alias="POSTGRES_PASSWORD")

    # --- Weights & Biases (optional) ---
    wandb_api_key: Optional[str] = Field(default=None, alias="WANDB_API_KEY")

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


# Singleton instance imported throughout the app
settings = Settings()