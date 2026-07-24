from pydantic import BaseModel
from typing import List


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