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
import re
from typing import List, Optional
from threading import Lock
from pathlib import Path
from config.settings import settings

from sentence_transformers import CrossEncoder

from medrag.retrieval.hybrid_search import hybrid_search

logger = logging.getLogger("medrag.retrieval")

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEFAULT_CANDIDATE_POOL_SIZE = 20
DEFAULT_TOP_N = 5

_cross_encoder_cache = None
_cross_encoder_lock = Lock()


def get_cross_encoder():
    global _cross_encoder_cache
    with _cross_encoder_lock:
        if _cross_encoder_cache is None:
            logger.info(f"Loading cross-encoder '{CROSS_ENCODER_MODEL}'...")
            encoder = CrossEncoder(CROSS_ENCODER_MODEL)
            if settings.rerank_backend == "onnx" and encoder.model.device.type == "cpu":
                from medrag.retrieval.onnx_reranker import OnnxReranker
                cache_dir = Path(__file__).resolve().parents[4] / ".medrag_cache"
                encoder = OnnxReranker(encoder, cache_dir, settings.rerank_threads)
                logger.info("FP32 ONNX reranker ready")
            _cross_encoder_cache = encoder
    return _cross_encoder_cache


def warmup_retrieval():
    """Load local encoders and run one pass before accepting user requests."""
    from medrag.retrieval.hybrid_search import embed_query_sparse
    embed_query_sparse("medical information")
    rerank("medical information", [{"payload": {"raw_text": "Medical information."}}], top_n=1)


def rerank(query_text: str, candidates: List[dict], top_n: int = DEFAULT_TOP_N) -> List[dict]:
    candidates = [c for c in candidates if not re.search(r"\(cid:\d+\)", c["payload"]["raw_text"])]
    if not candidates or top_n <= 0:
        return []
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
    *,
    full_corpus_evaluation: bool = False,
) -> List[dict]:
    """Curated-only by default; user_id adds that key's uploads.

    full_corpus_evaluation is a trusted internal opt-in passed to hybrid_search;
    it cannot be combined with user_id. Reranking never widens retrieval scope.
    """
    candidates = hybrid_search(
        client, query_text,
        limit=candidate_pool_size,
        per_signal_limit=candidate_pool_size,
        user_id=user_id,
        full_corpus_evaluation=full_corpus_evaluation,
    )
    return rerank(query_text, candidates, top_n=top_n)
