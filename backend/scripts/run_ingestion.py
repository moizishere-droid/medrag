"""
Run PubMed ingestion for all locked topics.

Run from the backend/ folder:
    cd backend
    python scripts/run_ingestion.py
"""

import sys
import os
import logging

# Allow running this script directly with backend/ as the working directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.settings import settings
from medrag.ingestion.pubmed_client import configure_entrez
from medrag.ingestion.pipeline import ingest_all_topics

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw", "pubmed"))


def main():
    configure_entrez(email=settings.pubmed_email, api_key=settings.ncbi_api_key)

    ingest_all_topics(
        output_dir=OUTPUT_DIR,
        target_count=130,
        has_api_key=bool(settings.ncbi_api_key),
    )


if __name__ == "__main__":
    main()