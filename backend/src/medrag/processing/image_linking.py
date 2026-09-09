"""
Links WHO images to the text chunks that reference them, via figure-caption
string matching ("Figure 2", "Fig. 3", etc. found inside a chunk's raw_text).

This is the follow-up step flagged as designed-but-not-implemented in the
Phase 7 report. It requires no new fields on Chunk or WhoImage:

  - Chunk.source_id is already the canonical document id used during
    chunking ("+".join(sorted(topics)), set in chunker.py's
    chunk_who_guideline) - so it doubles as the join key here.
  - WHO image filenames already encode page and in-page index
    (e.g. "*_page3_img1.png" - see image_embedder.py's COVER_PAGE_PATTERN),
    so no stored image_index field is required to reconstruct extraction
    order from the saved embeddings index alone.

Strategy: ordinal figure matching, not position/page matching. WHO guideline
clean_text has no page boundaries preserved (WHO text is chunked from the
fully merged document, per Phase 7's known limitation), so a chunk can't be
matched to "the image on the same page." Instead: images are sorted into
each document's reading order (page, then in-page index), which for WHO's
typical sequential figure numbering corresponds to figure order. A "Figure N"
mention in any chunk is matched to the Nth image extracted from that same
document.

This is a heuristic, not a guarantee - it assumes:
  1. Figures in the source PDF are numbered sequentially without gaps
     starting at 1, in the same order PyMuPDF extracts them.
  2. An image's topic set (from the embeddings dedup step) matches its
     guideline's topic set exactly, since both are used to compute the
     same canonical join key independently.
Both assumptions can break on a given document (e.g. a genuinely skipped
figure number, or a page-rendered vector diagram interleaved oddly with
embedded raster images). Rather than silently trusting the match, this
module reports match statistics so mismatches are visible and can be spot
-checked, in the same spirit as Phase 7's honest CLIP limitation writeup.

No fallback is applied when no "Figure N" mention exists anywhere in a
document's chunks for a given image - it is simply reported as unlinked.
A nearest-chunk-by-topic fallback was considered and rejected: with no
page metadata on chunks, "nearest" has no reliable meaning and would
produce confident-looking but unfounded links.
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

FIGURE_PATTERN = re.compile(r"\bfig(?:ure)?s?\.?\s*(\d+)", re.IGNORECASE)
IMAGE_FILENAME_ORDER_PATTERN = re.compile(r"_page(\d+)_img(\d+)\.png$")


def extract_figure_references(text: str) -> List[int]:
    """Find every 'Figure N' / 'Fig. N' style mention in text, in order of
    appearance. Sub-figure suffixes ('Figure 2a') are matched on the leading
    number only - the suffix is not distinguished."""
    return [int(m) for m in FIGURE_PATTERN.findall(text)]

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
    order (page, then in-page index) - this ordering stands in for figure
    order. canonical_id is computed the same way chunker.py computes
    Chunk.source_id ("+".join(sorted(topics))), so it lines up with chunks
    from the same underlying document without needing a shared literal id.
    """
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
) -> Tuple[List[dict], dict]:
    """
    Full pipeline: for every WHO document, scan its text chunks for
    'Figure N' mentions and link each to the Nth image extracted from that
    same document (1-indexed, matching natural figure numbering).

    Only chunk_type == "text" chunks are scanned - table chunks are
    row/cell data, not prose that references figures.

    Returns (links, stats):
      links - list of {chunk_id, point_id, image_filename, figure_number,
               canonical_id, match_type}, one entry per mention (a chunk
               mentioning two figures produces two entries; an image
               mentioned by two chunks produces two entries).
      stats - counts for sanity-checking the heuristic: how many documents
              had both images and chunks, how many figure mentions were
              found, how many fell outside the image count for their
              document (likely mis-numbered or non-sequential figures),
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
                ordinal = fig_num - 1

                if 0 <= ordinal < len(images):
                    image = images[ordinal]
                    links.append({
                        "chunk_id": chunk.chunk_id,
                        "point_id": chunk.point_id,
                        "image_filename": image.filename,
                        "figure_number": fig_num,
                        "canonical_id": canonical_id,
                        "match_type": "ordinal_caption",
                    })
                    linked_image_keys.add((canonical_id, image.filename))
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