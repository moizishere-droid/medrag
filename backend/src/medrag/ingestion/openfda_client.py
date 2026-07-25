"""
OpenFDA drug label client: fetch, parse, dedupe drug records per topic.
"""

import time
import logging
from typing import List, Tuple, Optional

import requests

from medrag.ingestion.models import DrugRecord

logger = logging.getLogger("medrag.ingestion")

OPENFDA_URL = "https://api.fda.gov/drug/label.json"


def fetch_drugs_raw(topic: str, limit: int = 150, max_retries: int = 3, api_key: Optional[str] = None) -> list:
    """
    Query OpenFDA for drugs whose indications mention this topic.
    Retries on timeout/connection errors; returns an empty list if all retries fail
    (the topic is skipped, not crashed, in that case).
    """
    params = {"search": f"indications_and_usage:{topic}", "limit": limit}
    if api_key:
        params["api_key"] = api_key

    for attempt in range(max_retries):
        try:
            response = requests.get(OPENFDA_URL, params=params, timeout=15)
            if response.status_code != 200:
                logger.warning(f"  OpenFDA returned status {response.status_code} for '{topic}'")
                return []
            data = response.json()
            return data.get("results", [])

        except requests.exceptions.RequestException as e:
            logger.warning(f"  Attempt {attempt + 1}/{max_retries} failed for '{topic}': {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                logger.error(f"  Giving up on '{topic}' after {max_retries} attempts")
                return []


def parse_drug_record(raw: dict, topic: str) -> DrugRecord:
    """
    Parse one raw OpenFDA result into a DrugRecord.
    Raises ValueError if the record lacks identifiable drug name data
    (a meaningful fraction of OpenFDA labels lack openfda metadata entirely).
    """
    openfda = raw.get("openfda", {})

    brand_name = openfda.get("brand_name", [None])[0]
    generic_name = openfda.get("generic_name", [None])[0]

    if not brand_name and not generic_name:
        raise ValueError("No brand_name or generic_name — cannot identify drug")

    return DrugRecord(
        brand_name=brand_name or generic_name,
        generic_name=generic_name or brand_name,
        drug_class=openfda.get("pharm_class_epc", [None])[0],
        indications_and_usage=" ".join(raw.get("indications_and_usage", [])),
        dosage_and_administration=" ".join(raw.get("dosage_and_administration", [])) or None,
        contraindications=" ".join(raw.get("contraindications", [])) or None,
        warnings_and_cautions=" ".join(raw.get("warnings_and_cautions", [])) or None,
        adverse_reactions=" ".join(raw.get("adverse_reactions", [])) or None,
        drug_interactions=" ".join(raw.get("drug_interactions", [])) or None,
        mechanism_of_action=" ".join(raw.get("mechanism_of_action", [])) or None,
        topic=topic,
    )


def parse_drugs_safe(raw_results: list, topic: str) -> Tuple[List[DrugRecord], List[dict]]:
    """Parse a batch, skipping and logging any that fail (e.g., missing drug identity)."""
    parsed = []
    failed = []

    for raw in raw_results:
        try:
            drug = parse_drug_record(raw, topic=topic)
            parsed.append(drug)
        except Exception as e:
            failed.append({"error": str(e)})

    return parsed, failed


def dedupe_drugs(drugs: List[DrugRecord]) -> List[DrugRecord]:
    """Keep only the first occurrence of each brand_name (case-insensitive)."""
    seen = set()
    deduped = []
    for drug in drugs:
        key = drug.brand_name.lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(drug)
    return deduped


def fetch_drugs_for_topic(
    topic: str,
    raw_limit: int = 150,
    target_count: int = 25,
    api_key: Optional[str] = None,
) -> Tuple[List[DrugRecord], List[dict]]:
    """
    Full OpenFDA pipeline for one topic: fetch -> parse safely -> dedupe -> cap.

    Not every topic reaches target_count — some conditions genuinely have fewer
    than 25 distinct FDA-labeled drugs (e.g., malnutrition, typhoid). That's
    expected and not treated as an error.
    """
    raw_results = fetch_drugs_raw(topic, limit=raw_limit, api_key=api_key)
    parsed, failed = parse_drugs_safe(raw_results, topic=topic)
    deduped = dedupe_drugs(parsed)
    capped = deduped[:target_count]

    return capped, failed