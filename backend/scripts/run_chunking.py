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

# WHO topics with a real guideline (24 of 36 - see docs/phase04_report.md)
WHO_TOPICS = [
    "tuberculosis", "hypertension", "diabetes", "obesity", "asthma", "copd",
    "coronary artery disease", "heart failure", "stroke", "hyperlipidemia",
    "pneumonia", "covid-19", "malaria", "hiv aids", "hepatitis b", "hepatitis c",
    "dengue fever", "typhoid", "depression", "anxiety disorder", "epilepsy",
    "malnutrition", "anemia in pregnancy", "breast cancer",
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
    for topic in WHO_TOPICS:
        guideline = load_guideline(topic, output_dir=RAW_WHO_DIR)
        if guideline is None:
            continue
        tables = load_who_tables(topic, output_dir=WHO_TABLE_DIR)
        table_dicts = [{"page_number": t.page_number, "table_data": t.table_data} for t in tables]

        chunks = chunk_who_guideline(guideline, table_dicts)
        save_chunks(chunks, source="who", topic=topic, output_dir=CHUNK_OUTPUT_DIR)
        total_chunks += len(chunks)
        logger.info(f"who/{topic}: {guideline.num_pages} pages, {len(tables)} tables -> {len(chunks)} chunks")
    logger.info(f"=== WHO chunking done: {total_chunks} total chunks ===")


def main():
    chunk_pubmed()
    chunk_openfda()
    chunk_who()


if __name__ == "__main__":
    main()