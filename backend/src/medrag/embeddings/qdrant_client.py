"""
Qdrant connection and collection management for MedRAG.

This module owns the two production collections:
  - medrag_text   (hybrid: named "dense" vector, 1536-dim
    text-embedding-3-small, cosine + named "sparse" vector, BM25 with
    IDF modifier, via fastembed's Qdrant/bm25 encoder — PubMed, OpenFDA,
    and WHO chunks all live here together)
  - medrag_images (512-dim, CLIP ViT-B-32 vectors, unnamed/single vector
    — WHO images only; no sparse/keyword search over images)

medrag_text uses named vectors (Phase 9+) so each point carries both a
dense semantic embedding and a sparse BM25 keyword vector side by side,
enabling hybrid retrieval (dense + sparse, fused via RRF in Phase 10)
from a single collection. medrag_images has no sparse counterpart and
keeps its original single unnamed vector.

Collection creation here is intentionally non-destructive: ensure_collections()
creates a collection only if it doesn't already exist. Dropping and
recreating a collection is a deliberate, rare operation (e.g. clearing out
stale test data, or a genuine schema change like the Phase 9 hybrid
migration) and is exposed separately via reset_collections() so it can
never happen by accident on a normal ingestion run.
"""

import logging
from uuid import uuid5, NAMESPACE_URL

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

logger = logging.getLogger("medrag.embeddings")

TEXT_COLLECTION = "medrag_text"
IMAGE_COLLECTION = "medrag_images"
TEXT_VECTOR_SIZE = 1536   # text-embedding-3-small
IMAGE_VECTOR_SIZE = 512   # CLIP ViT-B-32

# Named vector keys used on every medrag_text point (Phase 9+).
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


def get_qdrant_client(url: str = "http://localhost:6333") -> QdrantClient:
    """Create a Qdrant client. Does not itself verify connectivity -
    call client.get_collections() after this to confirm the server is
    actually reachable."""
    return QdrantClient(url=url)


def ensure_collections(client: QdrantClient) -> None:
    """Create medrag_text and medrag_images if they don't already exist.
    Safe to call on every ingestion run - never touches an existing
    collection's data.

    medrag_text is created with named dense + sparse vectors (hybrid
    schema, Phase 9+). If an older, pre-hybrid medrag_text (single
    unnamed vector) already exists, this function leaves it as-is -
    use reset_collections() to migrate it to the new schema."""
    if client.collection_exists(TEXT_COLLECTION):
        logger.info(f"Collection '{TEXT_COLLECTION}' already exists - leaving as-is")
    else:
        client.create_collection(
            collection_name=TEXT_COLLECTION,
            vectors_config={
                DENSE_VECTOR_NAME: qmodels.VectorParams(
                    size=TEXT_VECTOR_SIZE, distance=qmodels.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
                    modifier=qmodels.Modifier.IDF,
                ),
            },
        )
        logger.info(
            f"Created collection '{TEXT_COLLECTION}' "
            f"(dense: dim={TEXT_VECTOR_SIZE} cosine, sparse: IDF-modified BM25)"
        )

    if client.collection_exists(IMAGE_COLLECTION):
        logger.info(f"Collection '{IMAGE_COLLECTION}' already exists - leaving as-is")
    else:
        client.create_collection(
            collection_name=IMAGE_COLLECTION,
            vectors_config=qmodels.VectorParams(size=IMAGE_VECTOR_SIZE, distance=qmodels.Distance.COSINE),
        )
        logger.info(f"Created collection '{IMAGE_COLLECTION}' (dim={IMAGE_VECTOR_SIZE}, cosine)")


def reset_collections(client: QdrantClient) -> None:
    """Drop and recreate both collections, discarding all existing data.
    This is a deliberate, explicit operation - never called automatically
    by ensure_collections() or the ingestion pipeline. Use for a full
    rebuild (e.g. clearing stale test data, or a genuine vector schema
    change - such as the Phase 9 migration from a single unnamed
    medrag_text vector to named dense + sparse vectors, which cannot be
    applied to an existing collection and requires recreation)."""
    for name in (TEXT_COLLECTION, IMAGE_COLLECTION):
        if client.collection_exists(name):
            client.delete_collection(name)
            logger.info(f"Dropped collection '{name}'")
    ensure_collections(client)


def generate_image_point_id(filename: str) -> str:
    """Deterministic UUID5 from an image filename. Same filename always
    produces the same point_id, so re-running ingestion never creates
    duplicate Qdrant points for the same image, and any chunk's
    linked_images payload can reference this id without a separate
    lookup step."""
    return str(uuid5(NAMESPACE_URL, filename))