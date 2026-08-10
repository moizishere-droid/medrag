"""
Run chunking across all ingested PubMed, OpenFDA, and WHO data.

Run from the backend/ folder:
    cd backend
    python scripts/run_chunking.py
"""

import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from medrag.ingestion.storage import load_articles, load_drugs, load_guideline, load_who_tables
from medrag.ingestion.pipeline import TOPICS as PUBMED_TOPICS
from medrag.processing.chunker import chunk_pubmed_article, chunk_openfda_drug, chunk_who_guideline
from medrag.processing.storage import save_chunks

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("medrag.processing")

RAW_PUBMED_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw", "pubmed"))
RAW_OPENFDA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw", "openfda"))
RAW_WHO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw", "who"))
WHO_TABLE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "tables", "who"))
CHUNK_OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "processed", "chunks"))

# WHO topics with a real guideline (24 of 36 - see docs/phase04_report.md),
# grouped by underlying shared document (matching run_who_ingestion.py's
# TOPIC_DOCS groupings) - each group is chunked ONCE via chunk_who_guideline,
# then the identical resulting chunks are saved under every topic file in
# the group, so per-topic retrieval still works without duplicating the
# actual chunking computation or creating divergent chunk_id/source_id
# values for what is really the same content.
WHO_TOPIC_GROUPS = [
    ["tuberculosis"],
    ["hypertension"],
    ["diabetes"],
    ["obesity"],
    ["asthma", "copd"],
    ["coronary artery disease", "heart failure", "stroke", "hyperlipidemia"],
    ["pneumonia"],
    ["covid-19"],
    ["malaria"],
    ["hiv aids"],
    ["hepatitis b"],
    ["hepatitis c"],
    ["dengue fever"],
    ["typhoid"],
    ["depression", "anxiety disorder", "epilepsy"],
    ["malnutrition"],
    ["anemia in pregnancy"],
    ["breast cancer"],
]


def chunk_pubmed():
    """
    Same reasoning as OpenFDA: a single article's PMID can genuinely appear
    under more than one topic (confirmed in this project's data - ~10% of
    articles, e.g. anxiety-depression comorbidity papers, or anemia in
    pregnancy papers also covering malaria/malnutrition), discovered by
    scanning all topics' saved articles first rather than known upfront.
    """
    from collections import defaultdict

    pmid_to_topics = defaultdict(list)
    pmid_to_article = {}

    for topic in PUBMED_TOPICS:
        articles = load_articles(topic, output_dir=RAW_PUBMED_DIR)
        for article in articles:
            pmid_to_topics[article.pmid].append(topic)
            if article.pmid not in pmid_to_article:
                pmid_to_article[article.pmid] = article

    topic_to_chunks = defaultdict(list)
    total_chunks = 0
    total_unique_articles = len(pmid_to_article)

    for pmid, article in pmid_to_article.items():
        topics = pmid_to_topics[pmid]
        chunks = chunk_pubmed_article(article, topics=topics)
        total_chunks += len(chunks)
        for topic in topics:
            topic_to_chunks[topic].extend(chunks)

    for topic in PUBMED_TOPICS:
        chunks = topic_to_chunks.get(topic, [])
        save_chunks(chunks, source="pubmed", topic=topic, output_dir=CHUNK_OUTPUT_DIR)
        article_count = sum(1 for p in pmid_to_article if topic in pmid_to_topics[p])
        logger.info(f"pubmed/{topic}: {article_count} articles -> {len(chunks)} chunks")

    logger.info(
        f"=== PubMed chunking done: {total_unique_articles} unique articles, "
        f"{total_chunks} unique chunks across all topic files ==="
    )


def chunk_openfda():
    """
    Unlike WHO (where shared documents are known upfront via fixed URL
    groupings), OpenFDA's cross-topic drug sharing has to be discovered by
    scanning the actual saved data - the same brand_name can legitimately
    appear under several topics (e.g. naproxen across osteoarthritis,
    rheumatoid arthritis, etc.), and each occurrence must be merged into
    one chunked-once record rather than duplicated per topic, matching the
    fix already applied to WHO's shared documents.
    """
    from collections import defaultdict

    # Step 1: load every topic's drugs, group by brand_name to discover
    # which topics each unique drug actually appears under
    brand_to_topics = defaultdict(list)
    brand_to_drug = {}

    for topic in PUBMED_TOPICS:
        drugs = load_drugs(topic, output_dir=RAW_OPENFDA_DIR)
        for drug in drugs:
            key = drug.brand_name.lower().strip()
            brand_to_topics[key].append(topic)
            if key not in brand_to_drug:
                brand_to_drug[key] = drug  # first occurrence's full record is representative

    # Step 2: chunk each unique drug ONCE, with its full topics list
    topic_to_chunks = defaultdict(list)
    total_chunks = 0
    total_unique_drugs = len(brand_to_drug)

    for key, drug in brand_to_drug.items():
        topics = brand_to_topics[key]
        chunks = chunk_openfda_drug(drug, topics=topics)
        total_chunks += len(chunks)
        for topic in topics:
            topic_to_chunks[topic].extend(chunks)

    # Step 3: save the accumulated chunks under every topic file
    for topic in PUBMED_TOPICS:
        chunks = topic_to_chunks.get(topic, [])
        save_chunks(chunks, source="openfda", topic=topic, output_dir=CHUNK_OUTPUT_DIR)
        drug_count = sum(1 for k in brand_to_drug if topic in brand_to_topics[k])
        logger.info(f"openfda/{topic}: {drug_count} drugs -> {len(chunks)} chunks")

    logger.info(
        f"=== OpenFDA chunking done: {total_unique_drugs} unique drugs, "
        f"{total_chunks} unique chunks across all topic files ==="
    )


def chunk_who():
    total_chunks = 0
    total_saved_files = 0

    for group in WHO_TOPIC_GROUPS:
        primary_topic = group[0]
        guideline = load_guideline(primary_topic, output_dir=RAW_WHO_DIR)
        if guideline is None:
            continue

        tables = load_who_tables(primary_topic, output_dir=WHO_TABLE_DIR)
        table_dicts = [{"page_number": t.page_number, "table_data": t.table_data} for t in tables]

        # Chunked ONCE per group, not once per topic - avoids duplicate
        # spaCy computation and produces chunks with a shared canonical
        # chunk_id/source_id across every topic in the group
        chunks = chunk_who_guideline(guideline, table_dicts, topics=group)
        total_chunks += len(chunks)

        # Save the identical chunk set under every topic file in the group,
        # so per-topic retrieval/filtering still works normally
        for topic in group:
            save_chunks(chunks, source="who", topic=topic, output_dir=CHUNK_OUTPUT_DIR)
            total_saved_files += 1

        logger.info(
            f"who/{'+'.join(group)}: {guideline.num_pages} pages, {len(tables)} tables "
            f"-> {len(chunks)} chunks (saved under {len(group)} topic file(s))"
        )

    logger.info(f"=== WHO chunking done: {total_chunks} unique chunks across {total_saved_files} topic files ===")


def main():
    chunk_pubmed()
    chunk_openfda()
    chunk_who()


if __name__ == "__main__":
    main()