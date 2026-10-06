"""Integration tests for upload isolation against a REAL Qdrant engine.

The unit tests prove the filter has the right shape and that the write and read
paths agree on the key. These tests prove Qdrant actually enforces it, on BOTH the
dense and the sparse query, which is what keeps one user's uploads private.

Every point has an IDENTICAL dense and sparse vector, so both signals match every
point. If either signal lacked the filter, the other user's chunk would leak
through it and the set comparisons below would fail.
"""

import importlib
import uuid
from types import SimpleNamespace

import numpy as np
import pytest
from qdrant_client.http import models as qmodels

from medrag.embeddings.qdrant_client import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME

pytestmark = pytest.mark.integration

hs = importlib.import_module("medrag.retrieval.hybrid_search")
uu = importlib.import_module("medrag.ingestion.user_upload")

SPARSE_INDICES = [1, 2]


def point_id(chunk_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def make_point(chunk_id, dim, user_id=None):
    payload = {"chunk_id": chunk_id, "source": "who", "raw_text": f"text {chunk_id}"}
    if user_id is not None:  # curated points have NO user_id field at all
        payload["user_id"] = user_id
        payload["source"] = "user_upload"
        payload["upload_ready"] = True
    return qmodels.PointStruct(
        id=point_id(chunk_id),
        vector={
            DENSE_VECTOR_NAME: [1.0] + [0.0] * (dim - 1),
            SPARSE_VECTOR_NAME: qmodels.SparseVector(indices=SPARSE_INDICES, values=[1.0, 1.0]),
        },
        payload=payload,
    )


@pytest.fixture
def fake_embeddings(monkeypatch, temp_collection):
    dim = temp_collection.dim
    monkeypatch.setattr(hs, "embed_query_dense", lambda text: [1.0] + [0.0] * (dim - 1))
    monkeypatch.setattr(
        hs,
        "embed_query_sparse",
        lambda text: SimpleNamespace(indices=np.array(SPARSE_INDICES), values=np.array([1.0, 1.0])),
    )


@pytest.fixture
def seeded(qdrant_client, temp_collection, fake_embeddings):
    """Two curated chunks, one upload by user A, one upload by user B."""
    dim = temp_collection.dim
    qdrant_client.upsert(
        collection_name=temp_collection.name,
        points=[
            make_point("curated_1", dim),
            make_point("curated_2", dim),
            make_point("upload_a", dim, user_id="A"),
            make_point("upload_b", dim, user_id="B"),
        ],
    )


def visible_to(qdrant_client, user_id):
    results = hs.hybrid_search(qdrant_client, "query", limit=10, per_signal_limit=10, user_id=user_id)
    return {r["chunk_id"] for r in results}


def test_a_user_sees_the_curated_corpus_plus_only_their_own_uploads(qdrant_client, seeded):
    assert visible_to(qdrant_client, "A") == {"curated_1", "curated_2", "upload_a"}
    assert visible_to(qdrant_client, "B") == {"curated_1", "curated_2", "upload_b"}


def test_a_user_with_no_uploads_sees_only_the_curated_corpus(qdrant_client, seeded):
    assert visible_to(qdrant_client, "C") == {"curated_1", "curated_2"}


def test_without_a_user_id_only_curated_points_are_visible(qdrant_client, seeded):
    """Scripts that omit an isolation key must never see uploaded documents."""
    assert visible_to(qdrant_client, None) == {"curated_1", "curated_2"}
    results = hs.hybrid_search(qdrant_client, "query", limit=10, per_signal_limit=10)
    assert {r["chunk_id"] for r in results} == {"curated_1", "curated_2"}


def test_explicit_evaluation_includes_all_users_but_not_staged_uploads(qdrant_client, seeded, temp_collection):
    staged = make_point("staged_a", temp_collection.dim, user_id="A")
    staged.payload["upload_ready"] = False
    qdrant_client.upsert(collection_name=temp_collection.name, points=[staged])
    results = hs.hybrid_search(qdrant_client, "query", limit=10, per_signal_limit=10,
                               full_corpus_evaluation=True)
    assert {r["chunk_id"] for r in results} == {"curated_1", "curated_2", "upload_a", "upload_b"}
    assert visible_to(qdrant_client, "A") == {"curated_1", "curated_2", "upload_a"}
    assert visible_to(qdrant_client, None) == {"curated_1", "curated_2"}


def test_legacy_upload_without_isolation_metadata_is_not_curated(qdrant_client, seeded, temp_collection):
    point = make_point("legacy_upload", temp_collection.dim)
    point.payload["source"] = "user_upload"
    qdrant_client.upsert(collection_name=temp_collection.name, points=[point])
    assert visible_to(qdrant_client, None) == {"curated_1", "curated_2"}
    assert "legacy_upload" not in visible_to(qdrant_client, "A")


def test_uploaded_document_round_trips_through_the_real_write_path(
    qdrant_client, temp_collection, fake_embeddings, monkeypatch
):
    """chunk_user_upload -> embed_and_upsert_upload_chunks -> hybrid_search, with only
    OpenAI and the sparse encoder faked: the payload the writer produces is accepted
    by Qdrant and is filtered correctly by the reader."""
    dim = temp_collection.dim

    class FakeOpenAI:
        def __init__(self):
            self.embeddings = SimpleNamespace(create=self._create)

        def _create(self, model, input):
            data = [SimpleNamespace(embedding=[1.0] + [0.0] * (dim - 1)) for _ in input]
            return SimpleNamespace(data=data)

    class FakeSparse:
        def embed(self, texts):
            return (
                SimpleNamespace(indices=np.array(SPARSE_INDICES), values=np.array([1.0, 1.0]))
                for _ in texts
            )

    monkeypatch.setattr(uu, "sentence_based_chunk", lambda text, target_tokens: ["alpha.", "beta."])
    monkeypatch.setattr(uu, "get_sparse_model", lambda: FakeSparse())

    chunks = uu.chunk_user_upload("body", user_id="A", session_id="A", document_id="doc1", filename="labs.pdf")
    stored = uu.embed_and_upsert_upload_chunks(chunks, qdrant_client, FakeOpenAI())

    assert stored == 2
    assert visible_to(qdrant_client, "A") == {"doc1_upload_0", "doc1_upload_1"}
    assert visible_to(qdrant_client, "B") == set()
    assert visible_to(qdrant_client, None) == set()
    results = hs.hybrid_search(qdrant_client, "query", full_corpus_evaluation=True)
    assert {r["chunk_id"] for r in results} == {"doc1_upload_0", "doc1_upload_1"}
