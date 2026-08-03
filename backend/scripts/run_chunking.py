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
    total_chunks = 0
    for topic in PUBMED_TOPICS:
        articles = load_articles(topic, output_dir=RAW_PUBMED_DIR)
        chunks = [c for article in articles for c in chunk_pubmed_article(article)]
        save_chunks(chunks, source="pubmed", topic=topic, output_dir=CHUNK_OUTPUT_DIR)
        total_chunks += len(chunks)
        logger.info(f"pubmed/{topic}: {len(articles)} articles -> {len(chunks)} chunks")
    logger.info(f"=== PubMed chunking done: {total_chunks} total chunks ===")


def chunk_openfda():
    total_chunks = 0
    for topic in PUBMED_TOPICS:  # OpenFDA used the same 36-topic list
        drugs = load_drugs(topic, output_dir=RAW_OPENFDA_DIR)
        chunks = [c for drug in drugs for c in chunk_openfda_drug(drug)]
        save_chunks(chunks, source="openfda", topic=topic, output_dir=CHUNK_OUTPUT_DIR)
        total_chunks += len(chunks)
        logger.info(f"openfda/{topic}: {len(drugs)} drugs -> {len(chunks)} chunks")
    logger.info(f"=== OpenFDA chunking done: {total_chunks} total chunks ===")


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