"""
Data models for chunked content, ready for Phase 7 embedding.
"""

from pydantic import BaseModel
from typing import Optional


class Chunk(BaseModel):
    chunk_id: str          # unique id, e.g. "diabetes_pubmed_12345678_0"
    text: str                # contextually prefixed - this is what gets embedded in Phase 7
    raw_text: str             # unprefixed original content, for display/citation
    source: str                # "pubmed" | "openfda" | "who"
    topic: str
    source_id: str               # pmid, brand_name, or who topic - identifies the parent document
    chunk_index: int               # position within the parent document (0, 1, 2...)
    chunk_type: str = "text"        # "text" | "table" - tables are a special atomic chunk type
    metadata: Optional[dict] = None  # e.g. {"page_number": 12} for WHO chunks