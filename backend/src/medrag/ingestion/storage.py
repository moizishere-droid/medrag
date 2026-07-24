"""
Local JSONL storage for ingested articles — one file per topic.
"""

import json
from pathlib import Path
from typing import List, Set

from medrag.ingestion.models import Article


def save_articles(articles: List[Article], topic: str, output_dir: str) -> Path:
    """Append articles to data/raw/pubmed/{topic}.jsonl (one JSON object per line)."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = Path(output_dir) / f"{topic}.jsonl"

    with open(filepath, "a", encoding="utf-8") as f:
        for article in articles:
            f.write(article.model_dump_json() + "\n")

    return filepath


def load_articles(topic: str, output_dir: str) -> List[Article]:
    """Load all saved articles for a topic back into Article objects."""
    filepath = Path(output_dir) / f"{topic}.jsonl"
    articles = []
    if not filepath.exists():
        return articles

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            articles.append(Article(**data))
    return articles


def get_existing_pmids(topic: str, output_dir: str) -> Set[str]:
    """Return the set of PMIDs already saved for a topic, for idempotent re-runs."""
    filepath = Path(output_dir) / f"{topic}.jsonl"
    if not filepath.exists():
        return set()

    existing = set()
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            existing.add(data["pmid"])
    return existing