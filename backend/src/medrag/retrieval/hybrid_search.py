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

An omitted user_id retrieves only recognized curated sources with an empty
ownership field. An explicit user_id adds that exact key's uploads. BOTH
dense and sparse queries enforce the same filter. Only trusted internal
evaluation callers may opt into full_corpus_evaluation=True.
The API uses the owning chat's session_id as this retrieval key; uploads
are therefore visible only in that chat. Direct internal callers must use
an equally scoped identity key and must not substitute an account-wide
key when the application promises chat-scoped uploads.

"""

import logging
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

import openai
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from config.settings import settings
from medrag.generation.limits import EMBEDDING_TIMEOUT_SECONDS
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
        _openai_client = openai.OpenAI(api_key=settings.openai_api_key, timeout=EMBEDDING_TIMEOUT_SECONDS, max_retries=0)
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


def build_user_filter(
    user_id: Optional[str], *, full_corpus_evaluation: bool = False,
) -> qmodels.Filter:
    """Match recognized curated sources with empty ownership, optionally
    adding points whose user_id matches exactly.
    A missing isolation key restricts retrieval to the curated corpus.
    Trusted internal callers may explicitly include all users' uploads for
    evaluation; staged uploads remain hidden in every mode. This option must
    never be exposed as a client-controlled API parameter."""
    if type(full_corpus_evaluation) is not bool:
        raise ValueError("full_corpus_evaluation must be a boolean")
    if full_corpus_evaluation and user_id is not None:
        raise ValueError("full_corpus_evaluation cannot be combined with user_id")
    unpublished = qmodels.FieldCondition(key="upload_ready", match=qmodels.MatchValue(value=False))
    if full_corpus_evaluation:
        return qmodels.Filter(must_not=[unpublished])
    curated = qmodels.Filter(must=[
            qmodels.FieldCondition(key="source", match=qmodels.MatchAny(any=["pubmed", "openfda", "who"])),
            qmodels.IsEmptyCondition(is_empty=qmodels.PayloadField(key="user_id")),
        ])
    if user_id is None:
        curated.must_not = [unpublished]
        return curated
    return qmodels.Filter(
        must_not=[unpublished],
        should=[
            curated,
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
    *,
    full_corpus_evaluation: bool = False,
) -> List[dict]:
    """Search curated content by default, or curated + the exact user's uploads.

    full_corpus_evaluation=True is an internal opt-in to all published uploads
    and cannot be combined with user_id. Both signals always share the filter.
    """
    query_filter = build_user_filter(user_id, full_corpus_evaluation=full_corpus_evaluation)
    dense_vec = embed_query_dense(query_text)
    sparse_vec = embed_query_sparse(query_text)

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
