"""
Qdrant connection and collection management for MedRAG.

This module owns the two production collections:
  - medrag_text   (1536-dim, text-embedding-3-small vectors — PubMed,
    OpenFDA, and WHO chunks all live here together)
  - medrag_images (512-dim, CLIP ViT-B-32 vectors — WHO images only)

Collection creation here is intentionally non-destructive: ensure_collections()
creates a collection only if it doesn't already exist. Dropping and
recreating a collection is a deliberate, rare operation (e.g. clearing out
stale test data, or a full rebuild after a schema change) and is exposed
separately via reset_collections() so it can never happen by accident on
a normal ingestion run.
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


def get_qdrant_client(url: str = "http://localhost:6333") -> QdrantClient:
    """Create a Qdrant client. Does not itself verify connectivity -
    call client.get_collections() after this to confirm the server is
    actually reachable."""
    return QdrantClient(url=url)


def ensure_collections(client: QdrantClient) -> None:
    """Create medrag_text and medrag_images if they don't already exist.
    Safe to call on every ingestion run - never touches an existing
    collection's data."""
    specs = [
        (TEXT_COLLECTION, TEXT_VECTOR_SIZE),
        (IMAGE_COLLECTION, IMAGE_VECTOR_SIZE),
    ]
    for name, size in specs:
        if client.collection_exists(name):
            logger.info(f"Collection '{name}' already exists - leaving as-is")
            continue
        client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(size=size, distance=qmodels.Distance.COSINE),
        )
        logger.info(f"Created collection '{name}' (dim={size}, cosine)")


def reset_collections(client: QdrantClient) -> None:
    """Drop and recreate both collections, discarding all existing data.
    This is a deliberate, explicit operation - never called automatically
    by ensure_collections() or the ingestion pipeline. Use only for a full
    rebuild (e.g. clearing stale test data, or after a payload schema
    change that requires re-uploading everything)."""
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