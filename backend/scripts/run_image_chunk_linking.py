"""
Runner script: links WHO images to the text chunks that reference them via
figure-caption matching, and saves the result to
data/processed/embeddings/image_chunk_links.jsonl

Run from the backend/ folder, same convention as run_chunking.py:
    cd backend
    python scripts/run_image_chunk_linking.py

Reads:
  - WHO chunks (already produced by Phase 6 / run_chunking.py). WHO chunks
    are saved per-topic, with a shared document's chunks (identical
    chunk_id) written identically to every topic file in its group
    (WHO_TOPIC_GROUPS, imported from run_chunking.py) - so chunks are
    loaded per-topic here and deduped by chunk_id, the same pattern
    already used for WHO image dedup in image_embedder.py.
  - WHO image embeddings index (already produced by Phase 7 /
    run_image_embeddings.py) - only used here to recover each unique
    image's WhoImage record and its topics list; the vectors themselves
    aren't needed for this step.
"""

import logging

from medrag.processing.storage import load_chunks
from medrag.embeddings.storage import load_image_embeddings
from medrag.ingestion.models import WhoImage
from medrag.processing.image_linking import link_images_to_chunks, save_image_chunk_links

# WHO_TOPIC_GROUPS lives in run_chunking.py (same scripts/ folder) - reused
# here rather than redefined, so this stays in sync if that list changes.
from run_chunking import WHO_TOPIC_GROUPS

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("medrag.processing")

CHUNKS_DIR = "data/processed/chunks"
EMBEDDINGS_DIR = "data/processed/embeddings"


def load_all_who_chunks() -> list:
    """
    Load WHO chunks across every topic, deduped by chunk_id. Since a
    shared document's chunks are saved identically under every topic in
    its WHO_TOPIC_GROUPS group, loading topic-by-topic without dedup would
    count/link against the same chunk multiple times.
    """
    who_topics = [topic for group in WHO_TOPIC_GROUPS for topic in group]

    seen_chunk_ids = set()
    unique_chunks = []
    for topic in who_topics:
        for chunk in load_chunks(source="who", topic=topic, output_dir=CHUNKS_DIR):
            if chunk.chunk_id not in seen_chunk_ids:
                seen_chunk_ids.add(chunk.chunk_id)
                unique_chunks.append(chunk)

    return unique_chunks


def main():
    logger.info("Loading WHO chunks...")
    chunks = load_all_who_chunks()
    logger.info(f"  Loaded {len(chunks)} unique WHO chunks")

    logger.info("Loading WHO image index...")
    _, image_index = load_image_embeddings(EMBEDDINGS_DIR)

    # Reconstruct WhoImage records + their topics lists from the saved
    # index (filename, topics, page_number, image_type - no vectors needed).
    image_records = [
        WhoImage(
            topic=entry["topics"][0],
            page_number=entry["page_number"],
            image_index=0,  # not stored in the index; parsed from filename downstream
            filename=entry["filename"],
            width=0,        # not needed for linking
            height=0,       # not needed for linking
            image_type=entry["image_type"],
        )
        for entry in image_index
    ]
    topics_per_record = [entry["topics"] for entry in image_index]
    logger.info(f"  Loaded {len(image_records)} unique images")

    logger.info("Linking images to chunks via figure-caption matching...")
    links, stats = link_images_to_chunks(chunks, image_records, topics_per_record)

    logger.info(f"  {len(links)} links created")
    logger.info(f"  {stats['figure_mentions_found']} figure mentions found across all chunks")
    logger.info(f"  {stats['figure_mentions_out_of_range']} mentions fell outside their document's image count")
    logger.info(f"  {stats['unique_images_linked']}/{stats['total_images']} unique images linked")
    logger.info(f"  {stats['documents_with_neither_matched']} documents had images but no matching chunks")
    logger.info(f"  {stats['documents_with_neither_matched']} documents had images but no matching chunks")
    logger.info(f"  {stats.get('listing_chunks_skipped', 0)} List-of-Figures chunks skipped")

    path = save_image_chunk_links(links, EMBEDDINGS_DIR)
    logger.info(f"Saved links to {path}")


if __name__ == "__main__":
    main()