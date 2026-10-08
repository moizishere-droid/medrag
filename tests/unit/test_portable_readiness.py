from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from types import SimpleNamespace

spec = spec_from_file_location("portable_readiness", Path(__file__).resolve().parents[2] / "deploy" / "check_readiness.py")
readiness = module_from_spec(spec)
spec.loader.exec_module(readiness)


def test_public_configuration_rejects_local_defaults():
    failures = readiness.validate_environment({"AUTH_REQUIRED": "false", "AUTH_COOKIE_SECURE": "false", "POSTGRES_PASSWORD": "medragpassword", "NEO4J_PASSWORD": "medragpassword"})
    assert len(failures) == 5
    assert readiness.validate_environment({"AUTH_REQUIRED": "true", "AUTH_COOKIE_SECURE": "true", "POSTGRES_PASSWORD": "a" * 24, "NEO4J_PASSWORD": "b" * 24, "OPENAI_API_KEY": "test"}) == []


class GraphSession:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def run(self, query):
        assert "TREATS|CONTRAINDICATED_IN|CAUSES" in query
        return SimpleNamespace(single=lambda: {"relationships": 10})


def corpus_client(counts, dimensions=1536, sparse=True):
    def count(collection, count_filter, exact):
        from medrag.retrieval.hybrid_search import build_user_filter
        assert count_filter.must[0] == build_user_filter(None)
        assert exact
        return SimpleNamespace(count=counts[count_filter.must[1].match.value])
    return SimpleNamespace(get_collection=lambda _: SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors={"dense": SimpleNamespace(size=dimensions)}, sparse_vectors={"sparse": {}} if sparse else {}))), count=count)


def test_corpus_gate_rejects_empty_source_even_when_database_is_connected():
    failures, counts, relationships = readiness.check_corpus(corpus_client({"pubmed": 2, "openfda": 0, "who": 1}), SimpleNamespace(session=GraphSession))
    assert failures == ["No visible curated openfda chunks; provision the corpus first"]
    assert counts["openfda"] == 0 and relationships == 10


def test_corpus_gate_rejects_incompatible_vector_schema():
    failures, _, _ = readiness.check_corpus(corpus_client({"pubmed": 2, "openfda": 3, "who": 1}, dimensions=512, sparse=False), SimpleNamespace(session=GraphSession))
    assert len(failures) == 2
