"""
Full PubMed ingestion pipeline: search -> skip existing -> fetch -> parse -> save,
for one topic or the full locked topic list.
"""

import logging
from typing import Dict

from medrag.ingestion.pubmed_client import (
    search_pubmed,
    fetch_articles_raw,
    parse_articles_safe,
    rate_limit_delay,
)
from medrag.ingestion.storage import save_articles, get_existing_pmids

logger = logging.getLogger("medrag.ingestion")

# Locked Phase 2 topic list (36 conditions across major categories)
TOPICS = [
    "diabetes", "hypertension", "obesity", "hyperlipidemia",
    "asthma", "copd", "pneumonia", "tuberculosis",
    "coronary artery disease", "heart failure", "stroke", "arrhythmia",
    "malaria", "dengue fever", "hiv aids", "hepatitis b", "covid-19", "typhoid",
    "depression", "anxiety disorder",
    "peptic ulcer disease", "irritable bowel syndrome", "hepatitis c",
    "osteoarthritis", "rheumatoid arthritis", "osteoporosis",
    "hypothyroidism", "hyperthyroidism",
    "epilepsy", "migraine", "parkinson's disease",
    "chronic kidney disease",
    "breast cancer", "lung cancer",
    "anemia in pregnancy", "malnutrition",
]


def ingest_topic(topic: str, output_dir: str, target_count: int = 130, has_api_key: bool = True) -> Dict:
    """Run the full ingestion pipeline for a single topic.

    target_count is the TOTAL desired articles for this topic (not "more per run") —
    if we already have target_count or more, this is a no-op.
    """
    logger.info(f"Starting ingestion for topic: {topic}")

    existing_pmids = get_existing_pmids(topic, output_dir)
    logger.info(f"  Already have {len(existing_pmids)} articles for '{topic}'")

    remaining = target_count - len(existing_pmids)
    if remaining <= 0:
        logger.info(f"  Target already met for '{topic}' ({len(existing_pmids)}/{target_count}) — skipping")
        return {"topic": topic, "fetched": 0, "failed": 0, "skipped": len(existing_pmids)}

    # Search a bit deeper than 'remaining' in case some results overlap with existing PMIDs
    search_count = len(existing_pmids) + remaining
    all_pmids = search_pubmed(topic, max_results=search_count)
    rate_limit_delay(has_api_key=has_api_key)

    new_pmids = [p for p in all_pmids if p not in existing_pmids][:remaining]
    logger.info(f"  {len(new_pmids)} new articles to fetch (need {remaining} more to reach {target_count})")

    if not new_pmids:
        logger.info(f"  Nothing new to fetch for '{topic}'")
        return {"topic": topic, "fetched": 0, "failed": 0, "skipped": len(existing_pmids)}

    raw_records = fetch_articles_raw(new_pmids)
    rate_limit_delay(has_api_key=has_api_key)

    parsed, failed = parse_articles_safe(raw_records["PubmedArticle"], topic=topic)

    if parsed:
        save_articles(parsed, topic=topic, output_dir=output_dir)

    logger.info(f"  Saved {len(parsed)}, failed {len(failed)} for '{topic}'")
    if failed:
        logger.warning(f"  Failures: {failed}")

    return {"topic": topic, "fetched": len(parsed), "failed": len(failed), "skipped": len(existing_pmids)}


def ingest_all_topics(output_dir: str, target_count: int = 130, has_api_key: bool = True) -> list:
    """Run ingestion across the full locked TOPICS list."""
    logger.info(f"Total topics: {len(TOPICS)}")
    results = []
    for topic in TOPICS:
        result = ingest_topic(topic, output_dir=output_dir, target_count=target_count, has_api_key=has_api_key)
        results.append(result)

    total_fetched = sum(r["fetched"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    logger.info(f"=== DONE === Total fetched: {total_fetched}, Total failed: {total_failed}")

    return results