"""The local bootstrap must reject accidental invocation against other targets."""
import importlib.util
from pathlib import Path

import pytest


def load_helper():
    path = Path(__file__).resolve().parents[2] / "deploy" / "bootstrap_local.py"
    spec = importlib.util.spec_from_file_location("local_bootstrap_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("changes, message", [
    ({"MEDRAG_LOCAL_BOOTSTRAP": "false"}, "restricted"),
    ({"QDRANT_URL": "https://external.example"}, "Unexpected"),
    ({"NEO4J_URI": "bolt://external.example:7687"}, "Unexpected"),
    ({"POSTGRES_PASSWORD": ""}, "POSTGRES_PASSWORD"),
    ({"NEO4J_PASSWORD": ""}, "NEO4J_PASSWORD"),
])
def test_rejects_unsafe_configuration_before_database_access(monkeypatch, changes, message):
    values = {"MEDRAG_LOCAL_BOOTSTRAP": "true", "QDRANT_URL": "http://qdrant:6333",
              "NEO4J_URI": "bolt://neo4j:7687", "POSTGRES_PASSWORD": "synthetic", "NEO4J_PASSWORD": "synthetic"}
    values.update(changes)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match=message):
        load_helper().main()
