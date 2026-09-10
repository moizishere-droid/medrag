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
search-relevance data (MS MARCO). A biomedical-specific cross-encoder
was considered and not used here, since the general-purpose model is
the more standard choice and this project already has scispaCy scoped
separately (Phase 12) to handle medical-term precision.

Note on scores: ms-marco-MiniLM outputs a raw logit, not a bounded
probability or similarity score - negative values are normal and do not
by themselves mean "irrelevant". Only relative ordering within one
query's candidate pool is meaningful for ranking; the score's magnitude
and sign (validated during Phase 11 development) can additionally serve
as a rough per-query confidence signal - a candidate pool that tops out
negative suggests weak corpus coverage for that query, distinct from a
pool topping out strongly positive.
"""

import logging
from typing import List

from sentence_transformers import CrossEncoder

from medrag.retrieval.hybrid_search import hybrid_search

logger = logging.getLogger("medrag.retrieval")

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEFAULT_CANDIDATE_POOL_SIZE = 20
DEFAULT_TOP_N = 5

_cross_encoder_cache = None


def get_cross_encoder() -> CrossEncoder:
    """Cached cross-encoder - loading has real startup cost, so it's
    loaded once per process rather than per call."""
    global _cross_encoder_cache
    if _cross_encoder_cache is None:
        logger.info(f"Loading cross-encoder '{CROSS_ENCODER_MODEL}'...")
        _cross_encoder_cache = CrossEncoder(CROSS_ENCODER_MODEL)
    return _cross_encoder_cache


def rerank(query_text: str, candidates: List[dict], top_n: int = DEFAULT_TOP_N) -> List[dict]:
    """Score each candidate's raw_text against the query with the
    cross-encoder and return the top_n by that score, descending.
    candidates must be hybrid_search()-shaped dicts (each with a
    payload containing raw_text) - mutates each dict in place, adding
    a 'cross_score' key, and returns a new sorted+truncated list."""
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
) -> List[dict]:
    """Full pipeline: retrieve a wider candidate pool via hybrid_search()
    (Phase 10), then rerank it down to the top_n most relevant results
    via the cross-encoder. candidate_pool_size should be comfortably
    larger than top_n, since reranking is only useful if it has enough
    candidates to meaningfully reorder - retrieving exactly top_n and
    then reranking that same top_n gives the cross-encoder no chance to
    surface a relevant chunk that hybrid search ranked outside its own
    top N."""
    candidates = hybrid_search(
        client, query_text,
        limit=candidate_pool_size,
        per_signal_limit=candidate_pool_size,
    )
    return rerank(query_text, candidates, top_n=top_n)