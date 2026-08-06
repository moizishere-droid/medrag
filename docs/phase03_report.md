# Phase 3: OpenFDA Drug Data Ingestion — Report

## Phase Objective

Ingest structured drug data from OpenFDA for the 36 locked medical topics, normalizing it into a validated schema — building the foundation for the Phase 14 drug-disease knowledge graph. Originally planned alongside WHO Guidelines under one combined Phase 3, but split into its own phase given how differently each source needed to be handled.

## What Was Built

- **`DrugRecord` model** (Pydantic) — normalized schema for drug data: `brand_name, generic_name, drug_class, indications_and_usage, dosage_and_administration, contraindications, warnings_and_cautions, adverse_reactions, drug_interactions, mechanism_of_action, topic, source`.
- **OpenFDA client** (`openfda_client.py`):
  - `fetch_drugs_raw()` — queries OpenFDA's drug label API by topic, with timeout + retry logic for connection failures, and **exact-phrase search matching** (see Key Design Decisions).
  - `parse_drug_record()` / `parse_drugs_safe()` — parses raw JSON into `DrugRecord` objects, safely skipping records with no identifiable drug name.
  - `dedupe_drugs()` — removes duplicate brand names within a topic's results.
  - `fetch_drugs_for_topic()` — the full per-topic pipeline: fetch → parse safely → dedupe → cap at target count, with an optional `search_term` override decoupled from the stored topic label.
- **Storage** — `save_drugs()` writes to `data/raw/openfda/{topic}.jsonl`.
- **Runner script** (`backend/scripts/run_openfda_ingestion.py`) — production entry point, reused the same `TOPICS` list from Phase 2, with a permanent `SEARCH_TERM_OVERRIDES` map for topics whose label doesn't match real FDA wording.
- **`OPENFDA_API_KEY`** added to `settings.py` as an optional field.

## Key Design Decisions

1. **Target 15-25 usable drugs per topic (not PubMed's 130)** — a real medical condition typically has far fewer distinct approved drugs than research papers.
2. **Fetch 125-150 raw results per topic to compensate for a ~20% usable yield** — most OpenFDA drug labels lack the `openfda` metadata sub-object entirely (no `brand_name`/`generic_name`), making them unusable.
3. **Accept variable counts per topic rather than forcing exactly 25** — some conditions genuinely have far fewer distinct FDA-labeled drugs, and forcing uniform counts would mean fabricating or duplicating data.
4. **Overwrite (`"w"`) instead of append (`"a"`) when saving** — OpenFDA drug labels aren't a growing corpus like papers; each run re-fetches the current best matches fresh.
5. **Retry + timeout handling on every request** — a single dropped connection during a 36-topic loop shouldn't crash the entire batch.
6. **Exact-phrase search matching (added in revision — see below).**
7. **Decoupled `search_term` from stored `topic` (added in revision — see below).**

## Revision: Exact-Phrase Matching Fix

A thorough final review conducted during Phase 6 (prompted by investigating an unrelated WHO chunking issue) surfaced a real, previously-undetected accuracy problem in this phase's original data.

### The Problem

OpenFDA's search API is Elasticsearch-based. The original query — `indications_and_usage:{topic}` — was **unquoted**, meaning a multi-word topic like `"irritable bowel syndrome"` was interpreted as an **OR** query across the individual words, not an exact phrase. Since common words like "syndrome" appear across many unrelated drug labels (e.g. mentioned in unrelated warnings or interaction notes), this caused genuine false positives: **glimepiride, a diabetes-specific drug, was incorrectly filed under `irritable bowel syndrome`, `Parkinson's disease`, and `anemia in pregnancy`** — none of which it treats. Checking the full dataset found **123 of 383 unique brand names** appeared under multiple topics, many with no clinical justification.

### The Fix

`fetch_drugs_raw()` now wraps the search term in quotes (`indications_and_usage:"{topic}"`), forcing exact-phrase matching. Re-running the full batch confirmed the fix: cross-topic matches dropped from 123 to 94, and — critically — the *character* of the remaining matches changed from arbitrary noise to clinically coherent multi-use drugs (e.g. `diltiazem` correctly appearing under both `arrhythmia` and `hypertension`; `prednisone` correctly spanning `asthma`, `osteoarthritis`, `rheumatoid arthritis`, and `tuberculosis`).

### A Side Effect: Some Topics Wrongly Dropped to Near-Zero

Exact-phrase matching also revealed that a few project topic labels don't match how FDA labels are actually worded:
- `hiv aids` dropped from 25 to 1 drug — real labels say `"HIV-1"`, never the literal phrase `"hiv aids"`.
- `peptic ulcer disease` dropped to 3 — many labels say `"peptic ulcer"` or `"duodenal ulcer"` rather than the full compound phrase.

**Fix:** added an optional `search_term` parameter to `fetch_drugs_raw()`/`fetch_drugs_for_topic()`, decoupled from the topic label used everywhere else in the project (storage, PubMed, WHO). A `SEARCH_TERM_OVERRIDES` map was added **permanently** to `run_openfda_ingestion.py` itself (not a one-off patch script) so any future re-run — including a scheduled refresh — automatically applies the correct search terms rather than silently regressing:

```python
SEARCH_TERM_OVERRIDES = {
    "hiv aids": "HIV-1",
    "peptic ulcer disease": "peptic ulcer",
}
```

Re-fetching with these overrides confirmed the fix: `hiv aids` recovered to 25 drugs, `peptic ulcer disease` improved to 12.

### Investigated and Accepted as Genuine (Not Bugs)

A few remaining low-count topics were individually checked and confirmed to be honest results, not matching failures:
- `dengue fever` (0, even with a broader `"Dengue"` search term) — plausibly genuine, since FDA-approved dengue-specific treatment is extremely limited (the dengue vaccine is likely classified/labeled outside this drug-label endpoint entirely).
- `anemia in pregnancy` (0, OpenFDA's documented behavior for zero-match queries) — deliberately not broadened to just `"anemia"`, since that risked reintroducing the exact false-positive problem just fixed.
- `typhoid` (4) and `malnutrition` (2) — plausibly genuine, reflecting real limited FDA-approved treatment options for these conditions.

### Design Principle Established

A topic with zero or very few OpenFDA drugs is treated the same way the 12 WHO-guidance gaps were: an honest, accepted data limitation, not something to hide or force. Each of the three sources answers a different question (PubMed: what does research show; OpenFDA: what does the FDA label say; WHO: what are official global recommendations) — a gap in one source doesn't mean a topic lacks coverage overall, since the other two sources may still have full content. The RAG system's generation step (Phase 15) is responsible for stating a source-specific gap honestly rather than fabricating an answer.

## Results

- **Original run:** 766 usable drug records across 36 topics, 0 crashes, 3,186 raw results correctly skipped as unusable.
- **After the exact-phrase matching fix:** 607 records — a real reduction, reflecting removal of false-positive matches, not a data loss.
- **After the two search-term override fixes:** totals recovered where warranted (`hiv aids` and `peptic ulcer disease` both restored to realistic counts) while keeping the false-positive fix intact elsewhere.

## Files Created / Updated in This Revision

- `backend/src/medrag/ingestion/openfda_client.py` (updated — exact-phrase matching, `search_term` parameter)
- `backend/scripts/run_openfda_ingestion.py` (updated — permanent `SEARCH_TERM_OVERRIDES`)
- `data/raw/openfda/*.jsonl` (36 files, corrected data)
- `docs/phase03_report.md`