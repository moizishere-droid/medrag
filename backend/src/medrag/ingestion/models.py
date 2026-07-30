"""
Data models for ingested content.
"""

from pydantic import BaseModel
from typing import List, Optional


class Article(BaseModel):
    """
    A single ingested article, normalized to one consistent shape
    regardless of source (PubMed now; WHO/OpenFDA in later phases).
    """
    pmid: str
    title: str
    abstract: str
    authors: List[str]
    journal: str
    pub_date: str
    language: str
    topic: str
    source: str = "pubmed"
    url: str


class DrugRecord(BaseModel):
    """
    A single structured drug record from OpenFDA, normalized for use
    in retrieval and the Phase 14 drug-disease knowledge graph.
    """
    brand_name: str
    generic_name: str
    drug_class: Optional[str] = None
    indications_and_usage: str
    dosage_and_administration: Optional[str] = None
    contraindications: Optional[str] = None
    warnings_and_cautions: Optional[str] = None
    adverse_reactions: Optional[str] = None
    drug_interactions: Optional[str] = None
    mechanism_of_action: Optional[str] = None
    topic: str
    source: str = "openfda"


class Guideline(BaseModel):
    """
    A single WHO guideline document, extracted from its source PDF.
    Not every project topic has a dedicated WHO guideline — some conditions
    (e.g. osteoarthritis, migraine) are genuinely specialty-society territory
    instead, and are simply absent from this source.

    clean_text excludes detected tables (used as the primary field for
    chunking/embedding). raw_text is the unmodified extraction, kept as a
    fallback since bbox-based table exclusion can occasionally remove
    legitimate nearby prose (captions, footnotes) on dense, table-heavy pages.
    """
    title: str
    topic: str
    clean_text: str
    raw_text: str
    num_pages: int
    num_tables: int
    num_images: int
    source_url: str
    source: str = "who"


class WhoTable(BaseModel):
    """A single table extracted from a WHO guideline PDF via pdfplumber."""
    topic: str
    page_number: int
    table_data: list  # list of rows, each row a list of cell values


class WhoImage(BaseModel):
    """A single image associated with a WHO guideline PDF.

    image_type is 'embedded' for a real embedded raster image (PyMuPDF
    get_images), or 'rasterized_page' for a full-page render used to
    capture vector-drawn figures/diagrams/algorithms that have no
    embedded image object to extract (PDFs draw these with vector
    instructions, not embedded bitmaps).
    """
    topic: str
    page_number: int
    image_index: int
    filename: str
    width: int
    height: int
    image_type: str = "embedded"