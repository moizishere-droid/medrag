# Phase 2: PubMed Data Ingestion (Text)

## Phase Objective

Develop a robust data ingestion pipeline that automatically collects medical articles from PubMed, converts them into a consistent validated format, and stores them locally for use in later stages of the MedRAG system. The pipeline should be reusable, fault-tolerant, and support idempotent execution to avoid duplicate data.

---

## What Was Built

A complete pipeline that searches PubMed, fetches matching articles, parses them into a validated data model, and saves them to disk — proven first in a notebook, then lifted into clean production code.

* **`Article` model** (Pydantic) — normalized schema every ingested article must fit: `pmid, title, abstract, authors, journal, pub_date, language, topic, source, url`.
* **PubMed client** — wraps Biopython's `Bio.Entrez`:

  * `search_pubmed()` — ESearch, topic → list of PMIDs
  * `fetch_articles_raw()` — EFetch, PMIDs → raw XML records
  * `parse_article()` / `parse_articles_safe()` — raw XML → validated `Article` objects, with per-article error handling so one bad record doesn't crash a batch
  * `rate_limit_delay()` — respects PubMed's rate limits (~10 req/sec with an API key)
* **Storage layer** — `save_articles()`, `load_articles()`, `get_existing_pmids()`, all JSONL-based (one file per topic in `data/raw/pubmed/`)
* **Pipeline** — `ingest_topic()` (single topic, full search→fetch→parse→save flow) and `ingest_all_topics()` (loops the locked topic list)
* **Runner script** (`backend/scripts/run_ingestion.py`) — wires real config (`.env` via `settings.py`) into the pipeline for actual execution
* **`NCBI_API_KEY`** added to `settings.py` and `.env`

---

## Key Decisions & Reasoning

1. **Scope: 36 medical topics × 130 articles each (~4,680 total)** — widened from an initially considered 6 topics × 250, since ingestion is one-time/offline and broader coverage costs little extra time or money at this scale.
2. **Framing for the demo: "narrow scope now, clear roadmap to expand later."** The app will transparently show which topics it covers; out-of-scope questions should be honestly declined by the RAG system in later phases, not hallucinated.
3. **One-time batch ingestion, not continuous/live fetching** — data is fetched once, stored on disk; all later phases read from storage, never call PubMed directly at query time.
4. **JSONL over a single JSON array file** — easier to append to incrementally and safer for idempotent re-runs.
5. **Idempotency by design** — every run checks existing PMIDs first, so re-running the script never re-downloads or duplicates data.
6. **`configure_entrez()` as an explicit setup function** rather than importing `settings` directly inside the `medrag` package — keeps the package decoupled from where configuration happens to live; the runner script is responsible for wiring the two together.
7. **Modular production structure** — notebook logic was split by concern into `models.py` (data shape), `pubmed_client.py` (API + parsing), `storage.py` (file I/O), and `pipeline.py` (orchestration), rather than one flat file.

---

## Results

* Successfully ingested **4,680 unique PubMed articles** across **36 medical topics** (130 articles per topic).
* Achieved **0 parse failures** and **0 fetch failures** during the final ingestion run.
* Verified the complete ingestion workflow: **search → fetch → parse → validate → save → reload** using real PubMed data.
* Confirmed that re-running the production pipeline performs **no redundant downloads**, thanks to PMID-based duplicate detection and idempotent execution.
* Produced a clean, structured JSONL dataset that serves as the foundation for the document processing, embedding, retrieval, and generation phases of the MedRAG system.

---

## Challenges & Solutions

- **Additive over-fetch bug:** `target_count` was originally implemented as "fetch this many *more* articles every run" rather than "total desired per topic." This caused the first production run to add another 130 articles on top of the notebook's existing 130 for several topics before the bug was caught (diabetes, hypertension, obesity, hyperlipidemia, asthma reached ~260-270 before being caught).
  - **Fix:** `ingest_topic()` now checks `existing_pmids` against `target_count` first — if the target is already met, it skips entirely; otherwise it fetches only the shortfall.
  - **Cleanup:** a one-time script deduplicated and trimmed over-fetched topic files back to exactly 130 unique articles each. The cleanup script was deleted afterward since it has no ongoing purpose — the underlying bug is fixed in `pipeline.py`.
- **Inconsistent PubMed date fields** — some articles have only a year, others a full year-month-day. Solved by building the date string from whichever parts are present rather than assuming a fixed format.
- **Author name structure varies** — most authors have `LastName`/`ForeName`, but some entries are collective/group names (`CollectiveName`) with a different structure. Both cases handled explicitly.
- **Notebook import path** — `config.settings` wasn't importable from `notebooks/` by default; fixed by inserting `backend/`'s absolute path into `sys.path` at the top of the notebook.

## Files Created in This Phase

- `notebooks/phase02_pubmed_ingestion.ipynb`
- `backend/src/medrag/ingestion/models.py`
- `backend/src/medrag/ingestion/pubmed_client.py`
- `backend/src/medrag/ingestion/storage.py`
- `backend/src/medrag/ingestion/pipeline.py`
- `backend/scripts/run_ingestion.py`
- `backend/config/settings.py`
- `data/raw/pubmed/*.jsonl` (36 files, 130 articles each)
- `docs/phase02_report.md`