"""
PubMed E-utilities client: search, fetch, and parse articles via Biopython.

Entrez requires configuration (email + optional API key) before use.
Call configure_entrez() once at application/script startup — this module
deliberately does not import application config directly, keeping the
medrag package decoupled from where settings happen to live.
"""

import time
import logging
from typing import List, Optional

from Bio import Entrez

from medrag.ingestion.models import Article

logger = logging.getLogger("medrag.ingestion")


def configure_entrez(email: str, api_key: Optional[str] = None) -> None:
    """Configure Biopython's Entrez module. Call once before any other function here."""
    Entrez.email = email
    if api_key:
        Entrez.api_key = api_key


def rate_limit_delay(has_api_key: bool = True) -> None:
    """
    Pause briefly between requests to respect PubMed's rate limits.
    ~10 req/sec with an API key (0.11s delay), ~3 req/sec without (0.35s delay).
    """
    delay = 0.11 if has_api_key else 0.35
    time.sleep(delay)


def search_pubmed(topic: str, max_results: int = 130) -> List[str]:
    """Search PubMed for a topic, return a list of matching PMIDs."""
    handle = Entrez.esearch(db="pubmed", term=topic, retmax=max_results)
    record = Entrez.read(handle)
    handle.close()
    return record["IdList"]


def fetch_articles_raw(pmids: List[str]) -> dict:
    """Fetch full article records for a list of PMIDs. Returns Biopython's parsed XML structure."""
    ids = ",".join(pmids)
    handle = Entrez.efetch(db="pubmed", id=ids, rettype="abstract", retmode="xml")
    records = Entrez.read(handle)
    handle.close()
    return records


def _extract_authors(article_data: dict) -> List[str]:
    authors = []
    for author in article_data.get("AuthorList", []):
        if "LastName" in author and "ForeName" in author:
            authors.append(f"{author['LastName']} {author['ForeName']}")
        elif "CollectiveName" in author:
            authors.append(str(author["CollectiveName"]))
    return authors


def _extract_journal_and_date(article_data: dict) -> tuple[str, str]:
    journal = str(article_data["Journal"]["Title"])

    pub_date_data = article_data["Journal"]["JournalIssue"]["PubDate"]
    year = pub_date_data.get("Year", "")
    month = pub_date_data.get("Month", "")
    day = pub_date_data.get("Day", "")

    date_parts = [p for p in [year, month, day] if p]
    pub_date = "-".join(date_parts) if date_parts else "unknown"

    return journal, pub_date


def parse_article(pubmed_article: dict, topic: str) -> Article:
    """Parse one raw PubMed XML record into a validated Article object."""
    medline = pubmed_article["MedlineCitation"]
    article_data = medline["Article"]
    pmid = str(medline["PMID"])

    title = str(article_data["ArticleTitle"])
    language = article_data["Language"][0]

    abstract_parts = article_data.get("Abstract", {}).get("AbstractText", [])
    abstract = " ".join(str(part) for part in abstract_parts) if abstract_parts else ""

    authors = _extract_authors(article_data)
    journal, pub_date = _extract_journal_and_date(article_data)

    return Article(
        pmid=pmid,
        title=title,
        abstract=abstract,
        authors=authors,
        journal=journal,
        pub_date=pub_date,
        language=language,
        topic=topic,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    )


def parse_articles_safe(raw_articles: list, topic: str) -> tuple[List[Article], List[dict]]:
    """Parse a list of raw records, skipping (and logging) any that fail rather than crashing."""
    parsed = []
    failed = []

    for raw in raw_articles:
        try:
            article = parse_article(raw, topic=topic)
            parsed.append(article)
        except Exception as e:
            pmid = raw.get("MedlineCitation", {}).get("PMID", "unknown")
            failed.append({"pmid": str(pmid), "error": str(e)})
            logger.warning(f"Failed to parse PMID {pmid}: {e}")

    return parsed, failed