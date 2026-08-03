"""
Data models for chunked content, ready for Phase 7 embedding.
"""

import uuid
from pydantic import BaseModel
from typing import Optional, List


class Chunk(BaseModel):
    chunk_id: str            # unique, human-readable id, e.g. "diabetes_pubmed_12345678_0"
    point_id: str              # deterministic UUID5 derived from chunk_id - Qdrant (Phase 9)
                                 # requires point IDs to be an unsigned int or a UUID, not an
                                 # arbitrary string, so this is generated now to avoid rework later
    text: str                    # contextually prefixed - this is what gets embedded in Phase 7
    raw_text: str                  # unprefixed original content, for display/citation
    source: str                      # "pubmed" | "openfda" | "who"
    topics: List[str]                  # usually one topic; a WHO chunk from a document shared
                                         # across multiple project topics (e.g. the PEN package
                                         # covering both asthma and copd) lists all of them, so
                                         # the underlying content is stored/embedded exactly once
                                         # rather than duplicated per topic
    source_id: str                       # pmid, brand_name, or a canonical WHO document id
    chunk_index: int                       # position within the parent document (0, 1, 2...)
    chunk_type: str = "text"                # "text" | "table" - tables are a special atomic chunk type
    metadata: Optional[dict] = None           # e.g. {"page_number": 12}

    @staticmethod
    def make_point_id(chunk_id: str) -> str:
        """Deterministic UUID5 from a chunk_id, stable across re-runs."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))