"""Link exact figure identifiers through verified caption/page mappings.

Extraction order is never a figure identifier. Unverified figures remain
unlinked rather than falling back to cover photos or nearby images.
"""

import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

from medrag.ingestion.models import WhoImage
from medrag.processing.models import Chunk

logger = logging.getLogger("medrag.processing")

FIGURE_PATTERN = re.compile(r"\bfig(?:ure)?s?\.?\s*(\d+(?:\.\d+)*[a-z]?)", re.IGNORECASE)
IMAGE_FILENAME_ORDER_PATTERN = re.compile(r"_page(\d+)_img(\d+)\.png$")


def extract_figure_references(text: str) -> List[str]:
    """Find every 'Figure N' / 'Fig. N' style mention in text, in order of
    appearance. Decimal numbers and sub-figure suffixes are preserved;
    Figure 3.2 must never silently become Figure 3."""
    return [m.lower() for m in FIGURE_PATTERN.findall(text)]

def is_figure_listing_chunk(raw_text: str, min_distinct_figures: int = 3) -> bool:
    """
    Detect List-of-Figures / Table-of-Contents style chunks, which repeat
    the pattern 'Fig. N <title> <page#>' for several figures in a row.

    A genuine in-body caption chunk discusses one (occasionally two)
    figures inline with descriptive prose - it doesn't enumerate three or
    more distinct figure numbers back-to-back. The threshold is set above 2,
    not at 2, so a legitimate passage that cross-references a second figure
    ("as shown in Fig. 2, compare with Fig. 3") isn't wrongly excluded.
    A chunk mentioning 3+ distinct figure numbers is a much stronger and
    rarer signal specific to listing/ToC pages.
    """
    distinct_figures = set(extract_figure_references(raw_text))
    return len(distinct_figures) >= min_distinct_figures

def _image_sort_key(filename: str, fallback_page: int) -> Tuple[int, int]:
    """(page, in-page index) parsed from filename, matching the
    *_page{P}_img{I}.png pattern used throughout ingestion/embedding.
    Falls back to (page_number, 0) if a filename ever doesn't match the
    pattern, so sorting degrades gracefully rather than raising."""
    m = IMAGE_FILENAME_ORDER_PATTERN.search(filename)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (fallback_page, 0)


def group_images_by_document(
    image_records: List[WhoImage], topics_per_record: List[List[str]]
) -> Dict[str, List[WhoImage]]:
    """
    Group unique images by canonical document id, sorted into extraction
    order (page, then in-page index) for inventory only, never figure
    matching. canonical_id is computed the same way chunker.py computes
    Chunk.source_id ("+".join(sorted(topics))), so it lines up with chunks
    from the same underlying document without needing a shared literal id.
    """
    if len(image_records) != len(topics_per_record):
        raise ValueError("Image records and topics must have matching lengths")
    doc_images = defaultdict(list)
    for record, topics in zip(image_records, topics_per_record):
        canonical_id = "+".join(sorted(topics))
        doc_images[canonical_id].append(record)

    for canonical_id, images in doc_images.items():
        images.sort(key=lambda r: _image_sort_key(r.filename, r.page_number))

    return doc_images


def group_chunks_by_document(chunks: List[Chunk]) -> Dict[str, List[Chunk]]:
    """Group WHO chunks by source_id (already the canonical document id),
    in original document order (chunk_index)."""
    doc_chunks = defaultdict(list)
    for chunk in chunks:
        if chunk.source != "who":
            continue
        doc_chunks[chunk.source_id].append(chunk)

    for source_id, doc_chunk_list in doc_chunks.items():
        doc_chunk_list.sort(key=lambda c: c.chunk_index)

    return doc_chunks


def link_images_to_chunks(
    chunks: List[Chunk],
    image_records: List[WhoImage],
    topics_per_record: List[List[str]],
    verified_figures: Dict[tuple, dict] = None,
) -> Tuple[List[dict], dict]:
    """
    Full pipeline: for every WHO document, scan its text chunks for
    exact figure mentions and resolve them through verified_figures.
    Missing verified mappings produce no links.

    Only chunk_type == "text" chunks are scanned - table chunks are
    row/cell data, not prose that references figures.

    Returns (links, stats):
      links - list of {chunk_id, point_id, image_filename, figure_number,
               canonical_id, match_type}, one entry per mention (a chunk
               mentioning two figures produces two entries; an image
               mentioned by two chunks produces two entries).
      stats - counts for checking mapping coverage: how many documents
              had both images and chunks, how many figure mentions were
              found, how many had no verified caption/page mapping,
              and how many unique images ended up with zero links.
    """
    doc_images = group_images_by_document(image_records, topics_per_record)
    doc_chunks = group_chunks_by_document(chunks)

    links = []
    linked_image_keys = set()
    stats = {
        "total_images": len(image_records),
        "documents_with_images": len(doc_images),
        "documents_with_chunks": len(doc_chunks),
        "documents_with_neither_matched": 0,
        "figure_mentions_found": 0,
        "figure_mentions_out_of_range": 0,
        "listing_chunks_skipped": 0,
    }
    for canonical_id, images in doc_images.items():
        doc_chunk_list = doc_chunks.get(canonical_id)
        if not doc_chunk_list:
            # No text chunks exist for this image's document group - can't
            # link (e.g. a topic-set mismatch between image and guideline
            # extraction, or a document with images but no clean_text).
            stats["documents_with_neither_matched"] += 1
            continue

        for chunk in doc_chunk_list:
            if chunk.chunk_type != "text":
                continue

            if is_figure_listing_chunk(chunk.raw_text):
                stats["listing_chunks_skipped"] = stats.get("listing_chunks_skipped", 0) + 1
                logger.debug(
                    f"  Skipping likely List-of-Figures chunk {chunk.chunk_id} "
                    f"({len(set(extract_figure_references(chunk.raw_text)))} distinct figure numbers)"
                )
                continue

            for fig_num in extract_figure_references(chunk.raw_text):
                stats["figure_mentions_found"] += 1
                figure = (verified_figures or {}).get((canonical_id, fig_num))

                if figure:
                    links.append({
                        "chunk_id": chunk.chunk_id,
                        "point_id": chunk.point_id,
                        "image_filename": figure["filename"],
                        "figure_number": fig_num,
                        "canonical_id": canonical_id,
                        "match_type": "verified_caption",
                    })
                    linked_image_keys.add((canonical_id, figure["filename"]))
                else:
                    stats["figure_mentions_out_of_range"] += 1
                    logger.debug(
                        f"  '{canonical_id}': Figure {fig_num} mentioned in "
                        f"{chunk.chunk_id} but document has only {len(images)} images"
                    )

    stats["unique_images_linked"] = len(linked_image_keys)
    stats["images_unlinked"] = stats["total_images"] - stats["unique_images_linked"]

    return links, stats


def save_image_chunk_links(links: List[dict], output_dir: str) -> Path:
    """Save links as output_dir/image_chunk_links.jsonl, one link per row."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = Path(output_dir) / "image_chunk_links.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for link in links:
            f.write(json.dumps(link) + "\n")
    return path


def load_image_chunk_links(output_dir: str) -> List[dict]:
    """Load links back from output_dir/image_chunk_links.jsonl."""
    path = Path(output_dir) / "image_chunk_links.jsonl"
    links = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            links.append(json.loads(line))
    return links
