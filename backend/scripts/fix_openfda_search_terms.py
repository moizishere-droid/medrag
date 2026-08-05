"""
One-off targeted re-fetch for OpenFDA topics whose project label doesn't
match how FDA drug labels actually phrase the condition, causing exact
phrase matching (fixed in openfda_client.py) to wrongly return near-zero
results for topics that do have real matching drugs.

Run from backend/:
    python scripts/fix_openfda_search_terms.py

Delete this script after running - it's a one-time correction, not part of
the regular pipeline (search_term overrides could be folded into
run_openfda_ingestion.py's TOPIC_DOCS-style mapping if this pattern recurs).
"""

import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.settings import settings
from medrag.ingestion.openfda_client import fetch_drugs_for_topic
from medrag.ingestion.storage import save_drugs

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("medrag.ingestion")

OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw", "openfda"))

# topic -> better search term that matches real FDA label wording
SEARCH_TERM_OVERRIDES = {
    "hiv aids": "HIV-1",
    "dengue fever": "Dengue",
    "peptic ulcer disease": "peptic ulcer",
}


def main():
    api_key = getattr(settings, "openfda_api_key", None)

    for topic, search_term in SEARCH_TERM_OVERRIDES.items():
        drugs, failed = fetch_drugs_for_topic(topic, api_key=api_key, search_term=search_term)
        save_drugs(drugs, topic=topic, output_dir=OUTPUT_DIR)
        logger.info(f"{topic} (searched as '{search_term}'): saved {len(drugs)}, failed {len(failed)}")


if __name__ == "__main__":
    main()