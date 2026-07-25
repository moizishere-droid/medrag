# Phase 3: OpenFDA Drug Data Ingestion — Report

## Phase Objective

Ingest structured drug data from OpenFDA for the 36 locked medical topics, normalizing it into a validated schema — building the foundation for the Phase 14 drug-disease knowledge graph. Originally planned alongside WHO Guidelines under one combined Phase 3, but split into its own phase given how differently each source needed to be handled.

## What Was Built

- **`DrugRecord` model** (Pydantic) — normalized schema for drug data: `brand_name, generic_name, drug_class, indications_and_usage, dosage_and_administration, contraindications, warnings_and_cautions, adverse_reactions, drug_interactions, mechanism_of_action, topic, source`.
- **OpenFDA client** (`openfda_client.py`):
  - `fetch_drugs_raw()` — queries OpenFDA's drug label API by topic, with timeout + retry logic for connection failures.
  - `parse_drug_record()` / `parse_drugs_safe()` — parses raw JSON into `DrugRecord` objects, safely skipping records with no identifiable drug name.
  - `dedupe_drugs()` — removes duplicate brand names within a topic's results.
  - `fetch_drugs_for_topic()` — the full per-topic pipeline: fetch → parse safely → dedupe → cap at target count.
- **Storage** — `save_drugs()` added to `storage.py`, writing to `data/raw/openfda/{topic}.jsonl`.
- **Runner script** (`backend/scripts/run_openfda_ingestion.py`) — production entry point, reused the same `TOPICS` list from Phase 2.
- **`OPENFDA_API_KEY`** added to `settings.py` as an optional field.

## Key Design Decisions

1. **Target 15-25 usable drugs per topic (not PubMed's 130)** — a real medical condition typically has far fewer distinct approved drugs than research papers, so the same volume target didn't make sense here.
2. **Fetch 125-150 raw results per topic to compensate for a ~20% usable yield** — discovered that most OpenFDA drug labels lack the `openfda` metadata sub-object entirely (no `brand_name`/`generic_name`), making them unusable for our purposes; over-fetching was the only way to reliably reach the target count.
3. **Accept variable counts per topic rather than forcing exactly 25** — some conditions (e.g., malnutrition, typhoid, arrhythmia) genuinely have far fewer distinct FDA-labeled drugs. Forcing a uniform count would mean fabricating or duplicating data; the honest, medically accurate result is a variable count per topic.
4. **Overwrite (`"w"`) instead of append (`"a"`) when saving** — unlike PubMed's growing paper corpus, OpenFDA drug labels aren't cumulative; each run re-fetches the current best matches fresh, so overwriting avoids duplicate accumulation across repeated runs.
5. **Retry + timeout handling on every request** — a single dropped connection during a 36-topic loop shouldn't crash the entire batch; failures are retried twice, then logged and skipped.

## Results

- **766 usable drug records** saved across 36 topics, 0 crashes.
- 3,186 raw results were correctly identified and skipped as unusable (missing drug identity), not silently included as bad data.
- Production script (`run_openfda_ingestion.py`) independently verified to reproduce the exact same notebook results (766 saved / 3,186 failed).

## Challenges & Solutions

- **Only ~20% of raw OpenFDA results have identifiable drug metadata** — solved by over-fetching (125-150 raw per topic) and treating unidentifiable records as expected noise to skip, not errors to fix.
- **Uneven drug counts across topics** (14-25, with some as low as 2-10) — recognized as accurate real-world data rather than a bug; no forcing or synthetic padding applied.
- **`ConnectTimeout` crashed the initial batch run mid-way** — the first version of `fetch_drugs_raw()` had no timeout or retry handling, so one dropped connection killed the entire 36-topic loop. Fixed by adding a 15-second timeout and a 3-attempt retry with backoff; a topic that still fails after retries is logged and skipped rather than halting the run.

## Files Created

- `notebooks/phase03_openfda_ingestion.ipynb` (OpenFDA portion)
- `backend/src/medrag/ingestion/openfda_client.py`
- `backend/src/medrag/ingestion/models.py` (updated — added `DrugRecord`)
- `backend/src/medrag/ingestion/storage.py` (updated — added `save_drugs`)
- `backend/scripts/run_openfda_ingestion.py`
- `backend/config/settings.py` (updated — added `openfda_api_key`)
- `data/raw/openfda/*.jsonl` (36 files, variable counts, 766 total)
- `docs/phase03_report.md`