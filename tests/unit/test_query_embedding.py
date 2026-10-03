"""Unit tests for the thin embedding wrappers in hybrid_search.py / user_upload.py.

Each wrapper is only a few lines, but together they pin a contract that fails
SILENTLY if broken: the models used to embed a query must be the same models
that embedded the stored chunks. Vectors from different models are not
comparable, so retrieval would return plausible-looking but meaningless matches
with no exception raised.
"""

import importlib
from types import SimpleNamespace

import pytest

hs = importlib.import_module("medrag.retrieval.hybrid_search")
uu = importlib.import_module("medrag.ingestion.user_upload")


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    """Each module caches its client/model globally; isolate every test."""
    monkeypatch.setattr(hs, "_openai_client", None)
    monkeypatch.setattr(hs, "_sparse_model_cache", None)
    monkeypatch.setattr(uu, "_sparse_model_cache", None)


# --------------------------------------------------------------------------
# Contract between the query side and the upload (write) side
# --------------------------------------------------------------------------
def test_query_and_upload_use_the_same_embedding_models():
    assert hs.DENSE_EMBEDDING_MODEL == uu.DENSE_EMBEDDING_MODEL == "text-embedding-3-small"
    assert hs.SPARSE_MODEL_NAME == uu.SPARSE_MODEL_NAME == "Qdrant/bm25"


# --------------------------------------------------------------------------
# hybrid_search wrappers
# --------------------------------------------------------------------------
def test_openai_client_is_built_once_from_the_configured_key(monkeypatch):
    built = []

    class FakeOpenAI:
        def __init__(self, api_key):
            built.append(api_key)

    monkeypatch.setattr(hs.openai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(hs.settings, "openai_api_key", "sk-unit-test")

    first, second = hs.get_openai_client(), hs.get_openai_client()

    assert first is second
    assert built == ["sk-unit-test"]


def test_dense_embedding_sends_the_raw_query_to_the_configured_model(monkeypatch):
    calls = []

    def create(model, input):
        calls.append((model, input))
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])

    fake = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    monkeypatch.setattr(hs, "get_openai_client", lambda: fake)

    assert hs.embed_query_dense("metformin dosing") == [0.1, 0.2, 0.3]
    assert calls == [("text-embedding-3-small", "metformin dosing")]  # a str, not a list


def test_sparse_model_is_loaded_once_with_the_bm25_name(monkeypatch):
    constructed = []

    class FakeSparse:
        def __init__(self, model_name):
            constructed.append(model_name)

    monkeypatch.setattr(hs, "SparseTextEmbedding", FakeSparse)

    first, second = hs.get_sparse_model(), hs.get_sparse_model()

    assert first is second
    assert constructed == ["Qdrant/bm25"]


def test_sparse_embedding_returns_the_first_vector_of_a_single_text_batch(monkeypatch):
    seen = []
    vector = SimpleNamespace(indices=[1, 2], values=[0.5, 0.25])

    class FakeModel:
        def embed(self, texts):
            seen.append(texts)
            return iter([vector])

    monkeypatch.setattr(hs, "get_sparse_model", lambda: FakeModel())

    assert hs.embed_query_sparse("metformin") is vector
    assert seen == [["metformin"]]


# --------------------------------------------------------------------------
# user_upload sparse loader (lazy fastembed import)
# --------------------------------------------------------------------------
def test_upload_sparse_model_is_loaded_lazily_once_with_the_bm25_name(monkeypatch):
    import fastembed

    constructed = []

    class FakeSparse:
        def __init__(self, model_name):
            constructed.append(model_name)

    monkeypatch.setattr(fastembed, "SparseTextEmbedding", FakeSparse)

    first, second = uu.get_sparse_model(), uu.get_sparse_model()

    assert first is second
    assert constructed == ["Qdrant/bm25"]