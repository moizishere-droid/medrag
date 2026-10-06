"""
Text embedding generation via OpenAI's text-embedding-3-small.

Chunks are deduplicated by point_id before embedding - the same chunk
content can legitimately be saved under multiple topic files (see Phase 6's
final review: WHO shared documents, OpenFDA drugs used for multiple
conditions, PubMed papers relevant to multiple topics), but each unique
piece of content should only be embedded once. The resulting vector is
reused across every topic file that shares the same point_id when
inserting into Qdrant (Phase 9) - a Chunk's own `topics` field already
carries the full list of topics it belongs to.

Validated cell-by-cell in notebooks/phase07_embeddings.ipynb before being
lifted here - dedup, batching, retry, and the full pipeline were each
tested individually on real data before combining.
"""

import logging
import time
from typing import List, Tuple

import numpy as np
import tiktoken
from openai import OpenAI

from medrag.processing.models import Chunk

logger = logging.getLogger("medrag.embeddings")

ENCODING = tiktoken.get_encoding("cl100k_base")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

MAX_TOKENS_PER_BATCH = 250_000
MAX_CHUNKS_PER_BATCH = 500
MAX_TOKENS_PER_INPUT = 8191


def deduplicate_chunks(chunks: List[Chunk]) -> List[Chunk]:
    """Keep only the first occurrence of each point_id."""
    seen = set()
    unique = []
    for chunk in chunks:
        if chunk.point_id not in seen:
            seen.add(chunk.point_id)
            unique.append(chunk)
    return unique


def build_batches(chunks: List[Chunk]) -> List[List[Chunk]]:
    """Group chunks into batches respecting both a token budget and a chunk-count cap."""
    batches = []
    current_batch = []
    current_tokens = 0

    for chunk in chunks:
        chunk_tokens = len(ENCODING.encode(chunk.text))
        if not chunk.text.strip() or chunk_tokens > MAX_TOKENS_PER_INPUT:
            raise ValueError(f"Chunk {chunk.chunk_id} is empty or exceeds {MAX_TOKENS_PER_INPUT} tokens")

        if current_batch and (
            current_tokens + chunk_tokens > MAX_TOKENS_PER_BATCH
            or len(current_batch) >= MAX_CHUNKS_PER_BATCH
        ):
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(chunk)
        current_tokens += chunk_tokens

    if current_batch:
        batches.append(current_batch)

    return batches


def embed_batch_with_retry(client: OpenAI, texts: List[str], max_retries: int = 3) -> List[List[float]]:
    """Embed one batch of texts, with retry on transient failures."""
    if max_retries < 1:
        raise ValueError("max_retries must be positive")
    for attempt in range(max_retries):
        try:
            response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            data = response.data
            if len(data) != len(texts):
                raise ValueError("Embedding response count does not match input count")
            if data and all(hasattr(e, "index") for e in data):
                data = sorted(data, key=lambda e: e.index)
                if [e.index for e in data] != list(range(len(texts))):
                    raise ValueError("Embedding response indexes do not match inputs")
            return [e.embedding for e in data]
        except Exception as e:
            logger.warning(f"  Attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
            else:
                raise


def embed_chunks(chunks: List[Chunk], api_key: str = None) -> Tuple[List[Chunk], np.ndarray]:
    """
    Deduplicate chunks by point_id, then embed all unique chunks in batches.
    Returns (unique_chunks, embeddings) where embeddings[i] corresponds to
    unique_chunks[i].

    api_key is passed explicitly rather than relying on OpenAI() picking up
    OPENAI_API_KEY from the raw OS environment - consistent with how every
    other API client in this project (PubMed, OpenFDA, WHO) is configured
    via backend/config/settings.py rather than implicit env var pickup.
    """
    unique_chunks = deduplicate_chunks(chunks)
    if not unique_chunks:
        return [], np.empty((0, EMBEDDING_DIM), dtype=np.float32)
    client = OpenAI(api_key=api_key) if api_key else OpenAI()
    logger.info(f"  {len(chunks)} chunks -> {len(unique_chunks)} unique (deduplicated by point_id)")

    batches = build_batches(unique_chunks)
    logger.info(f"  Split into {len(batches)} batch(es)")

    all_embeddings = []
    for i, batch in enumerate(batches):
        texts = [c.text for c in batch]
        embeddings = embed_batch_with_retry(client, texts)
        all_embeddings.extend(embeddings)
        logger.info(f"  Batch {i + 1}/{len(batches)} embedded ({len(batch)} chunks)")

    return unique_chunks, np.array(all_embeddings, dtype=np.float32)
