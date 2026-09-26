"""
Cross-encoder reranking: takes a wider candidate pool from hybrid_search()
and rescopes it to a smaller, more precisely relevant top-N using a
cross-encoder that scores the query and each candidate chunk's raw_text
together, rather than comparing independently-encoded vectors.

This is deliberately a second pass on top of hybrid_search() (Phase 10),
never a replacement for it - a cross-encoder cannot be run over the full
corpus per query (no precomputation is possible, since the score only
exists for a specific (query, chunk) pair), so it only ever scores a
retrieval-narrowed candidate pool.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2 (sentence-transformers) - a
small, CPU-fast, general-purpose cross-encoder trained on real
search-relevance data (MS MARCO).

Phase 19: user_id is passed straight through to hybrid_search() - see
that module for the isolation mechanism. Reranking itself needs no
changes beyond that, since it only ever operates on whatever candidate
pool hybrid_search() already correctly filtered.
"""

import logging
from typing import List, Optional

from sentence_transformers import CrossEncoder

from medrag.retrieval.hybrid_search import hybrid_search

logger = logging.getLogger("medrag.retrieval")

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEFAULT_CANDIDATE_POOL_SIZE = 20
DEFAULT_TOP_N = 5

_cross_encoder_cache = None


def get_cross_encoder() -> CrossEncoder:
    global _cross_encoder_cache
    if _cross_encoder_cache is None:
        logger.info(f"Loading cross-encoder '{CROSS_ENCODER_MODEL}'...")
        _cross_encoder_cache = CrossEncoder(CROSS_ENCODER_MODEL)
    return _cross_encoder_cache


def rerank(query_text: str, candidates: List[dict], top_n: int = DEFAULT_TOP_N) -> List[dict]:
    model = get_cross_encoder()
    pairs = [(query_text, c["payload"]["raw_text"]) for c in candidates]
    scores = model.predict(pairs)

    for c, score in zip(candidates, scores):
        c["cross_score"] = float(score)

    return sorted(candidates, key=lambda c: c["cross_score"], reverse=True)[:top_n]


def search_with_reranking(
    client,
    query_text: str,
    candidate_pool_size: int = DEFAULT_CANDIDATE_POOL_SIZE,
    top_n: int = DEFAULT_TOP_N,
    user_id: Optional[str] = None,
) -> List[dict]:
    """user_id, when provided, restricts retrieval to the curated corpus
    plus this user's own uploaded documents (Phase 19) - passed straight
    through to hybrid_search()."""
    candidates = hybrid_search(
        client, query_text,
        limit=candidate_pool_size,
        per_signal_limit=candidate_pool_size,
        user_id=user_id,
    )
    return rerank(query_text, candidates, top_n=top_n)