"""Graph extraction scope and safe writes, with the graph driver faked."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from medrag.knowledge_graph import graph_ingestion as graph, neo4j_client


def test_graph_extracts_only_openfda_and_preserves_evidence(monkeypatch):
    extract = Mock(return_value={"diseases": ["Diabetes", "diabetes"]})
    monkeypatch.setattr(graph, "extract_medical_entities", extract)
    chunk = SimpleNamespace(source="user_upload", metadata={"field": "indications_and_usage"}, source_id="Metformin", raw_text="Evidence", chunk_id="label_1")
    assert graph.extract_relationships_from_chunk(chunk) == []
    extract.assert_not_called()
    chunk.source = "openfda"
    relationships = graph.extract_relationships_from_chunk(chunk)
    assert len(relationships) == 1 and relationships[0]["relationship"] == "TREATS"
    second = dict(relationships[0], source_chunk_id="label_2")
    assert graph.aggregate_relationships(relationships + [second])[0]["source_chunk_ids"] == ["label_1", "label_2"]


@pytest.mark.parametrize("batch_size", [0, -1])
def test_graph_rejects_invalid_batch_sizes_before_connecting(batch_size):
    driver = Mock()
    with pytest.raises(ValueError, match="positive"):
        graph.write_relationships_batched(driver, [], batch_size=batch_size)
    driver.session.assert_not_called()


def test_graph_rejects_relationship_injection_before_any_write():
    driver = Mock()
    with pytest.raises(ValueError, match="Unsupported"):
        graph.write_relationships_batched(driver, [{"relationship": "TREATS]->() DELETE d //"}])
    driver.session.assert_not_called()


def test_graph_driver_closes_after_failed_connectivity(monkeypatch):
    driver = Mock()
    driver.verify_connectivity.side_effect = ConnectionError("unreachable")
    monkeypatch.setattr(neo4j_client.GraphDatabase, "driver", lambda *a, **k: driver)
    with pytest.raises(ConnectionError):
        neo4j_client.get_neo4j_driver("bolt://localhost", "test", "test")
    driver.close.assert_called_once()
