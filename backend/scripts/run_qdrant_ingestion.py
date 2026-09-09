"""
Runner script: uploads PubMed, OpenFDA, and WHO text chunks (plus WHO
images and their chunk links) into Qdrant.

Run from the backend/ folder, same convention as other run_*.py scripts:
    cd backend
    python scripts/run_qdrant_ingestion.py

Phase 9+: medrag_text points now carry both a dense vector (Phase 6,
loaded from disk) and a sparse BM25 vector (computed here at upload time
via fastembed) under named vector keys, enabling hybrid retrieval. This
is a genuine schema change from the original Phase 8 single-unnamed-vector
collection - an existing pre-hybrid medrag_text collection is NOT
automatically migrated by a normal run (ensure_collections() leaves an
existing collection untouched). Pass --reset to drop and recreate both
collections under the new hybrid schema; this is required at least once
to move off an old Phase 8 collection, and is otherwise opt-in/destructive
for the same reason it always was: it discards existing data.

Reads:
  - PubMed / OpenFDA / WHO chunks (Phase 6, data/processed/chunks/)
  - PubMed / OpenFDA / WHO text embeddings (Phase 6, data/processed/embeddings/)
  - WHO image embeddings (Phase 7, data/processed/embeddings/)
  - WHO image-to-chunk links (Phase 7, data/processed/embeddings/image_chunk_links.jsonl)
"""

import argparse
import logging
from pathlib import Path

from medrag.embeddings.storage import load_embeddings, load_image_embeddings
from medrag.embeddings.qdrant_client import get_qdrant_client, ensure_collections, reset_collections
from medrag.embeddings.qdrant_ingestion import (
    dedupe_links,
    build_link_maps,
    upload_source_chunks,
    upload_images,
)
from medrag.processing.storage import load_chunks
from medrag.processing.image_linking import load_image_chunk_links

# WHO_TOPIC_GROUPS lives in run_chunking.py (same scripts/ folder) - reused
# here rather than redefined, so this stays in sync if that list changes.
from run_chunking import WHO_TOPIC_GROUPS

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # suppress per-request noise
logger = logging.getLogger("medrag.embeddings")

CHUNKS_DIR = "data/processed/chunks"
EMBEDDINGS_DIR = "data/processed/embeddings"


def load_all_chunks_for_source(source: str, chunks_dir: str) -> dict:
    """Load every saved topic file for `source`, deduped by chunk_id.
    Reads whatever topic files actually exist on disk rather than
    assuming a hardcoded topic list - each source's per-topic files
    were saved with duplicate lines by design (Phase 6 convention), so
    dedup by chunk_id collapses that back to one entry per unique chunk."""
    source_dir = Path(chunks_dir) / source
    lookup = {}
    for filepath in sorted(source_dir.glob("*.jsonl")):
        topic = filepath.stem
        for chunk in load_chunks(source=source, topic=topic, output_dir=chunks_dir):
            lookup.setdefault(chunk.chunk_id, chunk)
    return lookup


def load_who_chunks() -> dict:
    """WHO chunks use the hardcoded WHO_TOPIC_GROUPS (shared documents
    saved identically under every topic in their group) rather than a
    plain directory glob, matching the pattern already used in
    run_image_chunk_linking.py."""
    who_topics = [t for group in WHO_TOPIC_GROUPS for t in group]
    lookup = {}
    for topic in who_topics:
        for chunk in load_chunks(source="who", topic=topic, output_dir=CHUNKS_DIR):
            lookup.setdefault(chunk.chunk_id, chunk)
    return lookup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset", action="store_true",
        help=(
            "Drop and recreate both collections before uploading (destroys "
            "existing data). Required at least once to migrate an existing "
            "Phase 8 medrag_text collection to the Phase 9 hybrid "
            "(dense+sparse named vector) schema."
        ),
    )
    args = parser.parse_args()

    client = get_qdrant_client()
    client.get_collections()  # smoke test - raises if server unreachable

    if args.reset:
        logger.warning("--reset passed: dropping and recreating both collections")
        reset_collections(client)
    else:
        ensure_collections(client)

    # --- WHO: chunks + embeddings + image links ---
    logger.info("Loading WHO chunks, embeddings, and image links...")
    who_chunk_lookup = load_who_chunks()
    who_embeddings, who_index = load_embeddings("who", EMBEDDINGS_DIR)

    links = load_image_chunk_links(EMBEDDINGS_DIR)
    links = dedupe_links(links)
    chunk_to_images, image_to_chunks = build_link_maps(links)
    logger.info(f"  {len(chunk_to_images)} chunks have at least one linked image")
    logger.info(f"  {len(image_to_chunks)} images have at least one linked chunk")

    # --- PubMed / OpenFDA: chunks + embeddings ---
    logger.info("Loading PubMed chunks and embeddings...")
    pubmed_chunk_lookup = load_all_chunks_for_source("pubmed", CHUNKS_DIR)
    pubmed_embeddings, pubmed_index = load_embeddings("pubmed", EMBEDDINGS_DIR)

    logger.info("Loading OpenFDA chunks and embeddings...")
    openfda_chunk_lookup = load_all_chunks_for_source("openfda", CHUNKS_DIR)
    openfda_embeddings, openfda_index = load_embeddings("openfda", EMBEDDINGS_DIR)

    # --- Upload all three sources into medrag_text (dense + sparse per point) ---
    logger.info("Uploading text chunks (dense + sparse)...")
    total_text = 0
    total_text += upload_source_chunks(
        client, "who", who_chunk_lookup, who_embeddings, who_index,
        chunk_to_images=chunk_to_images,
    )
    total_text += upload_source_chunks(
        client, "pubmed", pubmed_chunk_lookup, pubmed_embeddings, pubmed_index,
    )
    total_text += upload_source_chunks(
        client, "openfda", openfda_chunk_lookup, openfda_embeddings, openfda_index,
    )
    logger.info(f"Total text points uploaded: {total_text}")

    # --- Upload WHO images into medrag_images ---
    logger.info("Uploading WHO images...")
    img_embeddings, img_index = load_image_embeddings(EMBEDDINGS_DIR)
    total_images = upload_images(client, img_index, img_embeddings, image_to_chunks=image_to_chunks)
    logger.info(f"Total image points uploaded: {total_images}")

    # --- Verify final counts server-side ---
    from medrag.embeddings.qdrant_client import TEXT_COLLECTION, IMAGE_COLLECTION
    text_count = client.count(collection_name=TEXT_COLLECTION, exact=True).count
    image_count = client.count(collection_name=IMAGE_COLLECTION, exact=True).count
    logger.info(f"Verified medrag_text count: {text_count}")
    logger.info(f"Verified medrag_images count: {image_count}")


if __name__ == "__main__":
    main()