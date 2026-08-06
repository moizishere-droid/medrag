"""
Run OpenFDA drug ingestion for all locked topics.

Run from the backend/ folder:
    cd backend
    python scripts/run_openfda_ingestion.py

Uses exact-phrase matching against OpenFDA's indications_and_usage field
(see openfda_client.fetch_drugs_raw for why this matters - an unquoted
multi-word search defaults to OR-matching between words, which was found to
cause real false positives, e.g. glimepiride, a diabetes drug, wrongly
matching under "irritable bowel syndrome" purely because its label
contained the word "syndrome" elsewhere).

SEARCH_TERM_OVERRIDES exists because exact-phrase matching means some
project topic labels no longer match real FDA label wording (e.g. FDA
labels say "HIV-1", never the literal phrase "hiv aids"). This map is a
permanent part of the pipeline, not a one-off patch - it must live here so
future re-runs (e.g. a scheduled refresh job) don't silently regress back
to the same mismatches. If a future re-run shows an unexpectedly low count
for a topic not already in this map, that's the signal to add it here too,
following the same investigation pattern used for the entries below.
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

# topic (as stored/used everywhere else in the project) -> actual OpenFDA
# search term (only differs where FDA's real label wording doesn't match
# the project's topic label). Confirmed via targeted investigation - see
# docs/phase03_report.md for the reasoning behind each entry.
SEARCH_TERM_OVERRIDES = {
    "hiv aids": "HIV-1",
    "peptic ulcer disease": "peptic ulcer",
}


def main():
    api_key = getattr(settings, "openfda_api_key", None)

    all_results = []
    for topic in TOPICS:
        search_term = SEARCH_TERM_OVERRIDES.get(topic)
        drugs, failed = fetch_drugs_for_topic(topic, api_key=api_key, search_term=search_term)
        save_drugs(drugs, topic=topic, output_dir=OUTPUT_DIR)
        logger.info(f"{topic}: saved {len(drugs)}, failed {len(failed)}")
        all_results.append({"topic": topic, "saved": len(drugs), "failed": len(failed)})

    total_saved = sum(r["saved"] for r in all_results)
    total_failed = sum(r["failed"] for r in all_results)
    logger.info(f"=== DONE === Total saved: {total_saved}, Total failed (no identity): {total_failed}")


if __name__ == "__main__":
    main()