"""
Generate embeddings for all chunks across PubMed, OpenFDA, and WHO.

Run from the backend/ folder:
    cd backend
    python scripts/run_embeddings.py

Loads every topic file per source, deduplicates by point_id (the same
chunk content can be saved under multiple topic files - see Phase 6's
final review), embeds each unique chunk exactly once, and saves the result
as a compact numpy array + JSONL index per source.
"""

import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.settings import settings
from medrag.processing.storage import load_chunks
from medrag.ingestion.pipeline import TOPICS as PUBMED_TOPICS
from medrag.embeddings.embedder import embed_chunks
from medrag.embeddings.storage import save_embeddings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("medrag.embeddings")

CHUNK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "processed", "chunks"))
EMBEDDING_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "processed", "embeddings"))

# WHO topics with a real guideline (24 of 36)
WHO_TOPICS = [
    "tuberculosis", "hypertension", "diabetes", "obesity", "asthma", "copd",
    "coronary artery disease", "heart failure", "stroke", "hyperlipidemia",
    "pneumonia", "covid-19", "malaria", "hiv aids", "hepatitis b", "hepatitis c",
    "dengue fever", "typhoid", "depression", "anxiety disorder", "epilepsy",
    "malnutrition", "anemia in pregnancy", "breast cancer",
]


def embed_source(source: str, topics: list):
    all_chunks = []
    for topic in topics:
        chunks = load_chunks(source=source, topic=topic, output_dir=CHUNK_DIR)
        all_chunks.extend(chunks)

    logger.info(f"{source}: {len(all_chunks)} chunk entries loaded across {len(topics)} topic files")

    unique_chunks, embeddings = embed_chunks(all_chunks, api_key=settings.openai_api_key)
    npy_path, index_path = save_embeddings(unique_chunks, embeddings, source=source, output_dir=EMBEDDING_DIR)

    logger.info(f"{source}: saved {len(unique_chunks)} unique embeddings -> {npy_path.name}")
    return len(unique_chunks)


def main():
    total = 0
    total += embed_source("pubmed", PUBMED_TOPICS)
    total += embed_source("openfda", PUBMED_TOPICS)
    total += embed_source("who", WHO_TOPICS)

    logger.info(f"=== DONE === {total} total unique embeddings generated")


if __name__ == "__main__":
    main()