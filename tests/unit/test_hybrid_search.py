"""Unit tests for hybrid_search() wiring, with embeddings and Qdrant faked.

Verifies that both signals are queried correctly, that the SAME user filter
reaches BOTH of them (the isolation guarantee), and that results are fused and
truncated. Whether Qdrant enforces the filter is covered by integration tests.
"""

import importlib
from types import SimpleNamespace

import numpy as np
import pytest
from qdrant_client.http import models as qmodels

from medrag.embeddings.qdrant_client import (
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    TEXT_COLLECTION,
)

# importlib returns the real module object even if retrieval/__init__.py
# re-exports a *function* named hybrid_search (which would shadow the submodule
# in `from medrag.retrieval import hybrid_search`).
hs = importlib.import_module("medrag.retrieval.hybrid_search")


class FakeQdrant:
    """Records query_points calls and returns canned hits per vector name."""

    def __init__(self, dense_hits, sparse_hits):
        self._hits = {DENSE_VECTOR_NAME: dense_hits, SPARSE_VECTOR_NAME: sparse_hits}
        self.calls = []

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(points=self._hits[kwargs["using"]])


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Replace the two embedding calls: no OpenAI request, no model download."""
    monkeypatch.setattr(hs, "embed_query_dense", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(
        hs,
        "embed_query_sparse",
        lambda text: SimpleNamespace(
            indices=np.array([1, 5]), values=np.array([0.5, 0.25])
        ),
    )


def test_queries_both_signals_with_correct_parameters(fake_embeddings, make_points):
    client = FakeQdrant(make_points("a"), make_points("b"))

    hs.hybrid_search(client, "metformin", limit=5, per_signal_limit=7)

    assert len(client.calls) == 2
    by_using = {call["using"]: call for call in client.calls}
    assert set(by_using) == {DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME}
    for call in client.calls:
        assert call["collection_name"] == TEXT_COLLECTION
        assert call["limit"] == 7  # per_signal_limit, not the final limit

    assert by_using[DENSE_VECTOR_NAME]["query"] == [0.1, 0.2, 0.3]
    sparse_query = by_using[SPARSE_VECTOR_NAME]["query"]
    assert isinstance(sparse_query, qmodels.SparseVector)
    assert sparse_query.indices == [1, 5]
    assert sparse_query.values == [0.5, 0.25]


def test_no_user_id_applies_curated_filter_to_both_signals(fake_embeddings, make_points):
    client = FakeQdrant(make_points("a"), make_points("b"))
    hs.hybrid_search(client, "q")
    expected = hs.build_user_filter(None)
    assert [call["query_filter"] for call in client.calls] == [expected, expected]


def test_same_user_filter_reaches_both_signals(fake_embeddings, make_points):
    """Isolation regression guard: a filter applied to only one signal would
    leak another user's uploads through the other."""
    client = FakeQdrant(make_points("a"), make_points("b"))

    hs.hybrid_search(client, "q", user_id="user-1")

    expected = hs.build_user_filter("user-1")
    assert len(client.calls) == 2
    for call in client.calls:
        assert call["query_filter"] == expected


def test_evaluation_filter_reaches_both_signals(fake_embeddings, make_points):
    client = FakeQdrant(make_points("a"), make_points("b"))
    hs.hybrid_search(client, "q", full_corpus_evaluation=True)
    expected = hs.build_user_filter(None, full_corpus_evaluation=True)
    assert [call["query_filter"] for call in client.calls] == [expected, expected]


def test_conflicting_scope_fails_before_embedding_or_query(monkeypatch):
    def unexpected(text):
        pytest.fail("Invalid scope must fail before embedding")
    monkeypatch.setattr(hs, "embed_query_dense", unexpected)
    client = FakeQdrant([], [])
    with pytest.raises(ValueError, match="cannot be combined"):
        hs.hybrid_search(client, "q", user_id="A", full_corpus_evaluation=True)
    assert client.calls == []


def test_fuses_signals_and_truncates_to_limit(fake_embeddings, make_points):
    client = FakeQdrant(
        dense_hits=make_points("a", "b", "c"),
        sparse_hits=make_points("b", "c", "d"),
    )

    out = hs.hybrid_search(client, "q", limit=2)

    assert [r["chunk_id"] for r in out] == ["b", "c"]
    assert set(out[0]) == {"chunk_id", "fused_score", "payload"}
    assert out[0]["fused_score"] == pytest.approx(1 / 62 + 1 / 61)
    assert out[0]["payload"]["chunk_id"] == "b"


def test_k_is_forwarded_to_fusion(fake_embeddings, make_points):
    client = FakeQdrant(make_points("a"), make_points("a"))
    assert hs.hybrid_search(client, "q", k=1)[0]["fused_score"] == pytest.approx(1.0)
    assert hs.hybrid_search(client, "q")[0]["fused_score"] == pytest.approx(2 / 61)
