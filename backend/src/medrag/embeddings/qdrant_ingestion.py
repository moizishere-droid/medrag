"""
Builds Qdrant points from chunks/images and uploads them in batches.

This module is source-agnostic: the same build_text_point()/upload_points()
logic handles PubMed, OpenFDA, and WHO chunks identically. WHO chunks
additionally carry a linked_images payload field (from Phase 7's
image-chunk linking); PubMed and OpenFDA chunks simply get an empty list
for that field, since they have no associated images.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from medrag.embeddings.qdrant_client import (
    TEXT_COLLECTION,
    IMAGE_COLLECTION,
    generate_image_point_id,
)
from medrag.processing.models import Chunk

logger = logging.getLogger("medrag.embeddings")

DEFAULT_BATCH_SIZE = 250


def dedupe_links(links: List[dict]) -> List[dict]:
    """Remove duplicate (chunk_id, image_filename) pairs from Phase 7's
    link records. The linker records one row per figure *mention*, not
    per unique pair - a chunk that references the same figure twice in
    its text produces two identical rows. This is separate from the
    List-of-Figures/ToC exclusion, which the linker itself already
    handles before producing any rows. Idempotent: safe to call on
    already-deduped input with no effect."""
    seen_pairs = set()
    deduped = []
    for link in links:
        pair = (link["chunk_id"], link["image_filename"])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        deduped.append(link)

    removed = len(links) - len(deduped)
    if removed:
        logger.info(f"  Deduped links: {len(links)} -> {len(deduped)} ({removed} duplicate mentions removed)")
    return deduped


def build_link_maps(links: List[dict]) -> Tuple[Dict[str, List[dict]], Dict[str, List[dict]]]:
    """Build bidirectional lookup maps from deduped link records:
      chunk_to_images: chunk_id -> [{filename, point_id, figure_number}, ...]
      image_to_chunks: image_filename -> [{chunk_id, point_id, figure_number}, ...]
    Built once so both directions are O(1) lookups at retrieval time,
    rather than scanning the full link list per query."""
    chunk_to_images = defaultdict(list)
    image_to_chunks = defaultdict(list)

    for link in links:
        image_point_id = generate_image_point_id(link["image_filename"])

        chunk_to_images[link["chunk_id"]].append({
            "filename": link["image_filename"],
            "point_id": image_point_id,
            "figure_number": link["figure_number"],
        })
        image_to_chunks[link["image_filename"]].append({
            "chunk_id": link["chunk_id"],
            "point_id": link["point_id"],
            "figure_number": link["figure_number"],
        })

    return dict(chunk_to_images), dict(image_to_chunks)


def build_text_point(
    chunk: Chunk,
    vector: np.ndarray,
    chunk_to_images: Optional[Dict[str, List[dict]]] = None,
) -> qmodels.PointStruct:
    """Build a single Qdrant point for a text chunk. linked_images is
    populated from chunk_to_images when provided (WHO chunks); PubMed
    and OpenFDA chunks pass no map and get an empty list, since they
    have no associated images."""
    payload = {
        "chunk_id": chunk.chunk_id,
        "source": chunk.source,
        "topics": chunk.topics,
        "source_id": chunk.source_id,
        "chunk_type": chunk.chunk_type,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "raw_text": chunk.raw_text,
        "metadata": chunk.metadata or {},
        "linked_images": (chunk_to_images or {}).get(chunk.chunk_id, []),
    }
    return qmodels.PointStruct(id=chunk.point_id, vector=vector.tolist(), payload=payload)


def build_image_point(
    filename: str,
    topics: List[str],
    page_number: int,
    image_type: str,
    vector: np.ndarray,
    image_to_chunks: Optional[Dict[str, List[dict]]] = None,
) -> qmodels.PointStruct:
    """Build a single Qdrant point for a WHO image. Uses the deterministic
    filename-based point_id so this always matches whatever id a chunk's
    linked_images payload already points to."""
    point_id = generate_image_point_id(filename)
    payload = {
        "filename": filename,
        "topics": topics,
        "page_number": page_number,
        "image_type": image_type,
        "linked_chunks": (image_to_chunks or {}).get(filename, []),
    }
    return qmodels.PointStruct(id=point_id, vector=vector.tolist(), payload=payload)


def upload_points(
    client: QdrantClient,
    collection_name: str,
    points: List[qmodels.PointStruct],
    batch_size: int = DEFAULT_BATCH_SIZE,
    label: str = "",
) -> int:
    """Upload points in batches rather than one giant request, so a very
    large source doesn't risk a request timeout or memory spike building
    everything at once, and so progress is visible / a mid-upload failure
    doesn't lose all prior work."""
    prefix = f"{label}: " if label else ""
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        client.upsert(collection_name=collection_name, points=batch)
        logger.info(f"  {prefix}uploaded {min(i + batch_size, len(points))}/{len(points)}")
    return len(points)


def upload_source_chunks(
    client: QdrantClient,
    source_name: str,
    chunk_lookup: Dict[str, Chunk],
    embeddings: np.ndarray,
    index_rows: List[dict],
    chunk_to_images: Optional[Dict[str, List[dict]]] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Build and upload all points for one source (pubmed / openfda / who)
    into the shared medrag_text collection. Rows whose chunk_id has no
    matching entry in chunk_lookup are skipped and counted, rather than
    raising - this can legitimately happen if embeddings and chunk files
    have drifted out of sync, and should be visible, not silent."""
    points = []
    skipped = 0
    for row, vector in zip(index_rows, embeddings):
        chunk = chunk_lookup.get(row["chunk_id"])
        if chunk is None:
            skipped += 1
            continue
        points.append(build_text_point(chunk, vector, chunk_to_images))

    logger.info(f"{source_name}: {len(points)} points to upload ({skipped} skipped, missing chunk)")
    return upload_points(client, TEXT_COLLECTION, points, batch_size=batch_size, label=source_name)


def upload_images(
    client: QdrantClient,
    img_index_rows: List[dict],
    img_embeddings: np.ndarray,
    image_to_chunks: Optional[Dict[str, List[dict]]] = None,
) -> int:
    """Build and upload all WHO image points into medrag_images. Small
    enough (76 images) to upload in a single batch."""
    points = [
        build_image_point(
            filename=row["filename"],
            topics=row["topics"],
            page_number=row["page_number"],
            image_type=row["image_type"],
            vector=vector,
            image_to_chunks=image_to_chunks,
        )
        for row, vector in zip(img_index_rows, img_embeddings)
    ]
    logger.info(f"Built {len(points)} image points")
    return upload_points(client, IMAGE_COLLECTION, points, label="images")