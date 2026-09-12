"""
Citation system: resolves the lightweight bracketed markers produced by
Phase 14's generation prompt (e.g. "[1]", "[1][3]") into structured
citation objects a frontend can render as clickable, verifiable source
links.

Deliberately separate from answer text rewriting: this module returns
the answer text UNCHANGED, alongside a resolved list of citation
objects. Whether/how to visually replace "[1]" with a link, footnote,
or hover card in the answer text is a presentation decision that
belongs with the frontend (Phase 20, Streamlit), not here.

Per-source citation display was investigated directly against real
data rather than assumed uniform across sources:
- WHO: has a real, resolvable source URL (from Phase 4's raw Guideline
  JSON, which was never carried through to Chunk.metadata - loaded
  separately here rather than by re-running chunking) and a title.
- PubMed: has a real title and a PMID, which resolves to a genuine
  public URL (https://pubmed.ncbi.nlm.nih.gov/{pmid}/).
- OpenFDA: has no title field and no captured identifier (set_id,
  application_number, etc.) that could construct a stable public URL -
  confirmed by inspecting the raw ingested record's fields directly.
  OpenFDA citations therefore show a constructed title (drug name +
  label section) with url=None. This is a documented, accepted
  limitation - not something silently worked around - consistent with
  the project's established pattern of stating real gaps plainly
  (e.g. the WHO 12-topic coverage gap, Phase 12/13's NER noise
  limitations).
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("medrag.citations")

PUBMED_URL_TEMPLATE = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

_who_source_url_cache: Optional[Dict[str, str]] = None


def build_who_source_url_lookup(who_raw_dir: str, use_cache: bool = True) -> Dict[str, str]:
    """Map WHO source_id (single-topic slug) -> source_url, read
    directly from Phase 4's saved raw Guideline JSON files
    (data/raw/who/*.json). Guideline.source_url was never carried
    through to Chunk.metadata during Phase 5 chunking, so this reads
    the original raw ingestion output instead of requiring a chunker
    change. Cached at module level - the WHO source set only changes
    when Phase 4 ingestion is re-run, not per citation lookup."""
    global _who_source_url_cache
    if use_cache and _who_source_url_cache is not None:
        return _who_source_url_cache

    lookup = {}
    for filepath in Path(who_raw_dir).glob("*.json"):
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        lookup[filepath.stem] = data.get("source_url")

    _who_source_url_cache = lookup
    return lookup


def get_who_source_url(source_id: str, who_source_urls: Dict[str, str]) -> Optional[str]:
    """WHO chunks shared across multiple topics carry a combined
    source_id ('topic1+topic2+...', set during Phase 5 chunking),
    while who_source_urls is keyed by individual topic filenames.
    Split on '+' and try each component - every topic in the group
    shares the same underlying document/URL, so the first match found
    is correct. Confirmed necessary: a naive direct-key lookup silently
    returned None for every multi-topic WHO document."""
    for topic in source_id.split("+"):
        if topic in who_source_urls:
            return who_source_urls[topic]
    return None


def get_display_info(payload: dict, who_source_urls: Dict[str, str]) -> Dict[str, Optional[str]]:
    """Return {title, url} for a chunk's payload, using the per-source
    metadata structure confirmed available for each source during
    Phase 15 development (see module docstring)."""
    source = payload["source"]

    if source == "who":
        title = payload["metadata"].get("title", payload.get("source_id", "WHO Guideline"))
        url = get_who_source_url(payload["source_id"], who_source_urls)
        return {"title": title, "url": url}

    if source == "openfda":
        drug_name = payload["source_id"]
        field = payload["metadata"].get("field", "")
        field_display = field.replace("_", " ").title()
        title = f"{drug_name} — FDA Label ({field_display})" if field else f"{drug_name} — FDA Label"
        return {"title": title, "url": None}

    if source == "pubmed":
        title = payload["metadata"].get("title", f"PubMed article {payload['source_id']}")
        pmid = payload["source_id"]
        return {"title": title, "url": PUBMED_URL_TEMPLATE.format(pmid=pmid)}

    logger.warning(f"Unrecognized source '{source}' for chunk {payload.get('chunk_id')}")
    return {"title": "Unknown source", "url": None}


def extract_used_citation_numbers(answer_text: str) -> set:
    """Find every bracketed number actually referenced in the generated
    answer text, e.g. '[1]' or '[1][3]' -> {1, 3}. Numbers the model
    didn't actually use are never resolved or returned."""
    return {int(n) for n in re.findall(r"\[(\d+)\]", answer_text)}


def build_citations(
    answer_text: str,
    results: List[dict],
    who_source_urls: Dict[str, str],
) -> List[dict]:
    """Resolve every citation marker actually used in the answer text
    back to a structured citation object. `results` must be the same
    reranked results list used to build the numbered context block
    passed to generation (Phase 14) - index N-1 corresponds to marker
    [N]. Marker numbers outside the valid range (e.g. a model
    hallucinating a citation number beyond the actual context size)
    are silently skipped rather than raising, since a malformed
    citation shouldn't break the whole response."""
    used_numbers = extract_used_citation_numbers(answer_text)
    citations = []
    for n in sorted(used_numbers):
        if n < 1 or n > len(results):
            logger.warning(f"Citation marker [{n}] is out of range for {len(results)} results - skipping")
            continue
        result = results[n - 1]
        payload = result["payload"]
        display = get_display_info(payload, who_source_urls)
        citations.append({
            "marker": n,
            "chunk_id": payload["chunk_id"],
            "source": payload["source"],
            "title": display["title"],
            "url": display["url"],
            "linked_images": payload.get("linked_images", []),
        })
    return citations