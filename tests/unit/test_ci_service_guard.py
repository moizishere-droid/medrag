"""The graph-seeding helper must refuse any production service configuration."""
import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize("override", [
    {"MEDRAG_CI": "false"},
    {"QDRANT_URL": "https://production.example.com"},
    {"NEO4J_URI": "bolt://localhost:7687"},
    {"POSTGRES_HOST": "production-db.example.com"},
])
def test_ci_seed_refuses_non_disposable_targets(monkeypatch, override):
    path = Path(__file__).resolve().parents[2] / "deploy" / "prepare_ci_services.py"
    spec = importlib.util.spec_from_file_location("ci_seed", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for key, value in {
        "MEDRAG_CI": "true", "QDRANT_URL": "http://vector-ci:6333",
        "NEO4J_URI": "bolt://graph-ci:7687", "POSTGRES_HOST": "postgres-ci",
        **override,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(module.requests, "get", lambda *a, **k: pytest.fail("Guard allowed network access"))
    monkeypatch.setattr(module.psycopg2, "connect", lambda *a, **k: pytest.fail("Guard allowed database access"))
    monkeypatch.setattr(module.GraphDatabase, "driver", lambda *a, **k: pytest.fail("Guard allowed graph access"))
    with pytest.raises(RuntimeError, match="CI"):
        module.main()
