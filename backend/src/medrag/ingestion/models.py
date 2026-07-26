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
    A single WHO guideline document, full text extracted from its source PDF.
    Not every project topic has a dedicated WHO guideline — some conditions
    (e.g. osteoarthritis, migraine) are genuinely specialty-society territory
    instead, and are simply absent from this source.
    """
    title: str
    topic: str
    full_text: str
    num_pages: int
    source_url: str
    source: str = "who"