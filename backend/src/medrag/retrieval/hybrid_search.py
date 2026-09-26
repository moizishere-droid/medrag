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
on incidental shared terms) - this is expected and is the direct
motivation for Phase 11's cross-encoder reranking, not something this
module tries to work around.

Phase 19: optional user_id parameter applies a Qdrant filter to BOTH
the dense and sparse queries - "either this point has no user_id field
at all (the curated corpus) OR its user_id matches this exact value."
This is the sole mechanism that keeps one user's uploaded documents
invisible to everyone else, while remaining visible across all of that
same user's own chat sessions (validated directly in the Phase 19
notebook: same user_id, different session_id, still retrievable;
different user_id, completely invisible).
"""

import logging
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

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
    global _openai_client
    if _openai_client is None:
        _openai_client = openai.OpenAI(api_key=settings.openai_api_key)
    return _openai_client


def get_sparse_model() -> SparseTextEmbedding:
    global _sparse_model_cache
    if _sparse_model_cache is None:
        logger.info(f"Loading sparse model '{SPARSE_MODEL_NAME}'...")
        _sparse_model_cache = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)
    return _sparse_model_cache


def embed_query_dense(text: str) -> List[float]:
    client = get_openai_client()
    response = client.embeddings.create(model=DENSE_EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def embed_query_sparse(text: str):
    model = get_sparse_model()
    return list(model.embed([text]))[0]


def build_user_filter(user_id: Optional[str]) -> Optional[qmodels.Filter]:
    """Build the Qdrant filter that enforces upload isolation: match
    points with no user_id field at all (the curated corpus, which
    never has this field) OR points whose user_id matches exactly.
    Returns None (no filter at all) when user_id is None."""
    if user_id is None:
        return None
    return qmodels.Filter(
        should=[
            qmodels.IsEmptyCondition(is_empty=qmodels.PayloadField(key="user_id")),
            qmodels.FieldCondition(key="user_id", match=qmodels.MatchValue(value=user_id)),
        ]
    )


def reciprocal_rank_fusion(
    result_lists: List[list],
    k: int = DEFAULT_RRF_K,
) -> Tuple[List[Tuple[str, float]], Dict[str, dict]]:
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
    user_id: Optional[str] = None,
) -> List[dict]:
    """user_id, when provided, restricts BOTH signals to the curated
    corpus plus this user's own uploaded documents (Phase 19)."""
    dense_vec = embed_query_dense(query_text)
    sparse_vec = embed_query_sparse(query_text)
    query_filter = build_user_filter(user_id)

    dense_results = client.query_points(
        collection_name=TEXT_COLLECTION,
        query=dense_vec,
        using=DENSE_VECTOR_NAME,
        query_filter=query_filter,
        limit=per_signal_limit,
    ).points

    sparse_results = client.query_points(
        collection_name=TEXT_COLLECTION,
        query=qmodels.SparseVector(
            indices=sparse_vec.indices.tolist(),
            values=sparse_vec.values.tolist(),
        ),
        using=SPARSE_VECTOR_NAME,
        query_filter=query_filter,
        limit=per_signal_limit,
    ).points

    ranked, payloads = reciprocal_rank_fusion([dense_results, sparse_results], k=k)

    return [
        {"chunk_id": chunk_id, "fused_score": score, "payload": payloads[chunk_id]}
        for chunk_id, score in ranked[:limit]
    ]