"""
Run OpenFDA drug ingestion for all locked topics.

Run from the backend/ folder:
    cd backend
    python scripts/run_openfda_ingestion.py
"""

import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.settings import settings
from medrag.ingestion.openfda_client import fetch_drugs_for_topic
from medrag.ingestion.storage import save_drugs
from medrag.ingestion.pipeline import TOPICS

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("medrag.ingestion")

OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw", "openfda"))


def main():
    api_key = getattr(settings, "openfda_api_key", None)

    all_results = []
    for topic in TOPICS:
        drugs, failed = fetch_drugs_for_topic(topic, api_key=api_key)
        save_drugs(drugs, topic=topic, output_dir=OUTPUT_DIR)
        logger.info(f"{topic}: saved {len(drugs)}, failed {len(failed)}")
        all_results.append({"topic": topic, "saved": len(drugs), "failed": len(failed)})

    total_saved = sum(r["saved"] for r in all_results)
    total_failed = sum(r["failed"] for r in all_results)
    logger.info(f"=== DONE === Total saved: {total_saved}, Total failed (no identity): {total_failed}")


if __name__ == "__main__":
    main()