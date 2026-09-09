"""
Hybrid retrieval: queries both the dense (semantic) and sparse (BM25)
vectors in medrag_text and fuses the two ranked result lists via
Reciprocal Rank Fusion (RRF).

Fusion is implemented client-side here (not via Qdrant's native
prefetch+FusionQuery API) as a deliberate choice: the installed
qdrant-client version's native RRF fusion uses a fixed k=1, which is
considerably more aggressive (near-"rank 1 anywhere wins") than the
standard k=60 used in the original RRF paper and in most published
hybrid-RAG work. The hand-implemented version here is tunable, matches
the well-known convention, and was validated directly against the
native path in the Phase 10 notebook before this choice was made.

Note: dense + sparse + fusion alone is known to surface some
low-relevance results (e.g. bibliography/reference-list chunks that sit
near a topic in embedding space without discussing it, or BM25 matches
on incidental shared terms) — this is expected and is the direct
motivation for Phase 11's cross-encoder reranking, not something this
module tries to work around.
"""

import logging
from collections import defaultdict
from typing import List, Dict, Tuple

import openai
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from config.settings import settings
from medrag.embeddings.qdrant_client import TEXT_COLLECTION, DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME

logger = logging.getLogger("medrag.retrieval")

DENSE_EMBEDDING_MODEL = "text-embedding-3-small"
SPARSE_MODEL_NAME = "Qdrant/bm25"
DEFAULT_RRF_K = 60

_openai_client = None
_sparse_model_cache = None


def get_openai_client() -> openai.OpenAI:
    """Cached OpenAI client, keyed off settings.openai_api_key."""
    global _openai_client
    if _openai_client is None:
        _openai_client = openai.OpenAI(api_key=settings.openai_api_key)
    return _openai_client


def get_sparse_model() -> SparseTextEmbedding:
    """Cached fastembed BM25 encoder - same model used to build the
    sparse vectors stored in Qdrant during Phase 9 ingestion. Using a
    different sparse encoder here would produce vectors in an
    incompatible term-hash space."""
    global _sparse_model_cache
    if _sparse_model_cache is None:
        logger.info(f"Loading sparse model '{SPARSE_MODEL_NAME}'...")
        _sparse_model_cache = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)
    return _sparse_model_cache


def embed_query_dense(text: str) -> List[float]:
    """Embed a query string with the same model used for all stored
    chunk embeddings (text-embedding-3-small) - a query embedded with a
    different model would land in an unrelated vector space."""
    client = get_openai_client()
    response = client.embeddings.create(model=DENSE_EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def embed_query_sparse(text: str):
    """Embed a query string with the same BM25 encoder used for all
    stored chunk sparse vectors. Returns a fastembed SparseEmbedding
    (has .indices / .values)."""
    model = get_sparse_model()
    return list(model.embed([text]))[0]


def reciprocal_rank_fusion(
    result_lists: List[list],
    k: int = DEFAULT_RRF_K,
) -> Tuple[List[Tuple[str, float]], Dict[str, dict]]:
    """Fuse multiple ranked result lists (each a list of Qdrant
    ScoredPoint objects with payload['chunk_id']) using Reciprocal Rank
    Fusion. Each result contributes 1/(k + rank) to its chunk's running
    fused score, rank starting at 1 - a chunk appearing in multiple
    lists accumulates contributions from each. Returns (ranked list of
    (chunk_id, fused_score) sorted descending, chunk_id -> payload map)."""
    fused_scores: Dict[str, float] = defaultdict(float)
    chunk_payloads: Dict[str, dict] = {}

    for results in result_lists:
        for rank, r in enumerate(results, start=1):
            chunk_id = r.payload["chunk_id"]
            fused_scores[chunk_id] += 1.0 / (k + rank)
            chunk_payloads[chunk_id] = r.payload

    ranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
    return ranked, chunk_payloads


def hybrid_search(
    client: QdrantClient,
    query_text: str,
    limit: int = 10,
    per_signal_limit: int = 10,
    k: int = DEFAULT_RRF_K,
) -> List[dict]:
    """Run dense and sparse retrieval against medrag_text independently,
    then fuse the two ranked lists via RRF.

    per_signal_limit controls how many results each individual signal
    (dense, sparse) contributes before fusion - kept separate from the
    final `limit` so a caller can widen the candidate pool per signal
    without changing how many final fused results are returned.

    Returns a list of {chunk_id, fused_score, payload} dicts, sorted by
    fused_score descending, capped at `limit`."""
    dense_vec = embed_query_dense(query_text)
    sparse_vec = embed_query_sparse(query_text)

    dense_results = client.query_points(
        collection_name=TEXT_COLLECTION,
        query=dense_vec,
        using=DENSE_VECTOR_NAME,
        limit=per_signal_limit,
    ).points

    sparse_results = client.query_points(
        collection_name=TEXT_COLLECTION,
        query=qmodels.SparseVector(
            indices=sparse_vec.indices.tolist(),
            values=sparse_vec.values.tolist(),
        ),
        using=SPARSE_VECTOR_NAME,
        limit=per_signal_limit,
    ).points

    ranked, payloads = reciprocal_rank_fusion([dense_results, sparse_results], k=k)

    return [
        {"chunk_id": chunk_id, "fused_score": score, "payload": payloads[chunk_id]}
        for chunk_id, score in ranked[:limit]
    ]