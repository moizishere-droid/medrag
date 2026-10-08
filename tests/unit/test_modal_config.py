import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("modal_config_test", Path(__file__).resolve().parents[2] / "deploy/modal_config.py")
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


def valid():
    return {"OPENAI_API_KEY": "synthetic", "PUBMED_EMAIL": "test@example.com", "QDRANT_URL": "https://example.qdrant.io", "QDRANT_API_KEY": "synthetic",
            "NEO4J_URI": "neo4j+s://example.databases.neo4j.io", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "synthetic",
            "POSTGRES_HOST": "example.neon.tech", "POSTGRES_PORT": "5432", "POSTGRES_DB": "neondb", "POSTGRES_USER": "demo", "POSTGRES_PASSWORD": "synthetic",
            "PGSSLMODE": "require", "MEDRAG_PUBLIC_ORIGIN": "https://demo.modal.run"}


def test_valid_cloud_environment():
    assert config.validate_modal_environment(valid()) == "https://demo.modal.run"


@pytest.mark.parametrize("key,value", [("QDRANT_API_KEY", ""), ("POSTGRES_HOST", "localhost"),
    ("QDRANT_URL", "http://localhost:6333"), ("NEO4J_URI", "bolt://neo4j:7687"),
    ("MEDRAG_PUBLIC_ORIGIN", "http://demo.modal.run"), ("MEDRAG_PUBLIC_ORIGIN", "https://demo.modal.run/api"), ("PGSSLMODE", "disable")])
def test_rejects_insecure_or_local_hosted_settings(key, value):
    values = valid()
    values[key] = value
    with pytest.raises(ValueError):
        config.validate_modal_environment(values)


def test_qdrant_key_is_passed_without_being_logged(monkeypatch):
    from medrag.embeddings import qdrant_client
    calls = []
    monkeypatch.setenv("QDRANT_API_KEY", "synthetic-cloud-key")
    monkeypatch.setattr(qdrant_client, "QdrantClient", lambda **kwargs: calls.append(kwargs))
    qdrant_client.get_qdrant_client("https://example.qdrant.io")
    assert calls == [{"url": "https://example.qdrant.io", "api_key": "synthetic-cloud-key"}]
