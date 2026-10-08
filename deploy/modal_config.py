"""Validate hosted demo settings without logging secrets."""
from urllib.parse import urlparse


def validate_modal_environment(env):
    required = ("OPENAI_API_KEY", "PUBMED_EMAIL", "QDRANT_URL", "QDRANT_API_KEY", "NEO4J_URI",
                "NEO4J_USER", "NEO4J_PASSWORD", "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
                "POSTGRES_USER", "POSTGRES_PASSWORD", "MEDRAG_PUBLIC_ORIGIN")
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise ValueError("Missing Modal settings: " + ", ".join(missing))
    origin = urlparse(env["MEDRAG_PUBLIC_ORIGIN"])
    if origin.scheme != "https" or not origin.hostname or origin.path not in ("", "/") or origin.query or origin.fragment or origin.username:
        raise ValueError("MEDRAG_PUBLIC_ORIGIN must be an HTTPS origin")
    if urlparse(env["QDRANT_URL"]).scheme != "https":
        raise ValueError("Hosted Qdrant must use HTTPS")
    if not env["NEO4J_URI"].startswith("neo4j+s://"):
        raise ValueError("Hosted Neo4j must use verified TLS: neo4j+s://")
    if env.get("PGSSLMODE") != "require":
        raise ValueError("PostgreSQL must require TLS")
    for name in ("QDRANT_URL", "NEO4J_URI", "POSTGRES_HOST"):
        value = env[name]
        host = urlparse(value).hostname if "://" in value else value
        if not host or host.lower() in {"localhost", "127.0.0.1", "postgres", "qdrant", "neo4j", "host.docker.internal"}:
            raise ValueError(name + " must point to a cloud database, not the local Docker stack")
    return env["MEDRAG_PUBLIC_ORIGIN"].rstrip("/")
