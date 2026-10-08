import gzip
import json

import pytest

from medrag.knowledge_graph.prepared_graph import corpus_fingerprint, load_prepared_graph


def artifact(tmp_path, **changes):
    chunks = tmp_path / "chunks"
    chunks.mkdir()
    source = chunks / "topic.jsonl"
    source.write_text(json.dumps({"chunk_id": "curated-one", "source": "openfda"}) + "\n")
    row = {"chemical": "Drug", "chemical_normalized": "drug", "disease": "Disease",
           "disease_normalized": "disease", "relationship": "TREATS", "source_chunk_ids": ["curated-one"]}
    row.update(changes)
    path = tmp_path / "graph.json.gz"
    with gzip.open(path, "wt") as stream:
        json.dump({"schema_version": 1, "corpus_sha256": corpus_fingerprint(chunks), "relationships": [row]}, stream)
    return path, chunks


def test_valid_curated_artifact(tmp_path):
    path, chunks = artifact(tmp_path)
    assert len(load_prepared_graph(path, chunks)) == 1


def test_changed_corpus_is_rejected(tmp_path):
    path, chunks = artifact(tmp_path)
    (chunks / "topic.jsonl").write_text('{}\n')
    with pytest.raises(ValueError, match="does not match"):
        load_prepared_graph(path, chunks)


@pytest.mark.parametrize("changes, message", [
    ({"source_chunk_ids": ["private-upload"]}, "non-curated"),
    ({"relationship": "UNKNOWN"}, "Unsupported"),
    ({"chemical": ""}, "Invalid"),
])
def test_invalid_graph_evidence_is_rejected(tmp_path, changes, message):
    path, chunks = artifact(tmp_path, **changes)
    with pytest.raises(ValueError, match=message):
        load_prepared_graph(path, chunks)
