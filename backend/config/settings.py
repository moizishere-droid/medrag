from pydantic_settings import BaseSettings,SettingsConfigDict # class that automatically reads your .env file.
from pydantic import Field
from typing import Optional
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2] # project root directory.
_ENV_FILE = _PROJECT_ROOT / ".env" # .env file located in the project root directory.


class Settings(BaseSettings):
    # OpenAI
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")

    # PubMed E-utilities
    pubmed_email: str = Field(..., alias="PUBMED_EMAIL")
    ncbi_api_key: Optional[str] = Field(default=None, alias="NCBI_API_KEY")

    # Qdrant
    qdrant_url: Optional[str] = Field(default=None, alias="QDRANT_URL")

    # Neo4j
    neo4j_uri: Optional[str] = Field(default=None, alias="NEO4J_URI")
    neo4j_user: Optional[str] = Field(default=None, alias="NEO4J_USER")
    neo4j_password: Optional[str] = Field(default=None, alias="NEO4J_PASSWORD")

    # PostgreSQL
    postgres_host: Optional[str] = Field(default=None, alias="POSTGRES_HOST")
    postgres_port: Optional[int] = Field(default=None, alias="POSTGRES_PORT")
    postgres_db: Optional[str] = Field(default=None, alias="POSTGRES_DB")
    postgres_user: Optional[str] = Field(default=None, alias="POSTGRES_USER")
    postgres_password: Optional[str] = Field(default=None, alias="POSTGRES_PASSWORD")

    # Weights & Biases
    wandb_api_key: Optional[str] = Field(default=None, alias="WANDB_API_KEY")

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


# Singleton instance imported throughout the app
settings = Settings()  # settings.openai_api_key --> can be accessed throughout the app.