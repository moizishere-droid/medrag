# Phase: WHO Guidelines Ingestion — Report

## Phase Objective

Ingest real WHO clinical guideline documents (PDFs) for the project's 36 topics, extract their full text, and normalize into a validated schema — completing the third and final planned data source alongside PubMed (research literature) and OpenFDA (structured drug data). Split out from the originally combined "Phase 3: WHO + OpenFDA" into its own phase, given how differently WHO's data needed to be sourced and handled.

## What Was Built

- **`Guideline` model** (Pydantic) — schema for a WHO guideline document: `title, topic, full_text, num_pages, source_url, source`.
- **WHO client** (`who_client.py`):
  - `resolve_who_pdf_url()` — resolves an old, now-broken WHO IRIS handle (e.g. `10665/344424`) through IRIS's DSpace REST API (handle → item UUID → ORIGINAL bundle → bitstream) into a working direct PDF download URL.
  - `fetch_who_guideline()` — downloads a guideline PDF (with a browser-like `User-Agent`, required to avoid a 403) and extracts its full text via `pypdf`.
- **Storage** — `save_guideline()` / `load_guideline()` added to `storage.py`, one JSON file per topic in `data/raw/who/`. Also added `load_drugs()` for consistency with the other two sources (was missing from Phase 3).
- **Runner script** (`backend/scripts/run_who_ingestion.py`) — production entry point with 24 hardcoded, pre-resolved final download URLs (the resolver itself is a discovery tool, not a runtime dependency of this script).

## Key Design Decisions

1. **Manual source curation, not automated topic search** — unlike PubMed/OpenFDA, WHO's IRIS repository has no public search API. Real guideline documents were identified per topic via manual web search, then resolved to working URLs programmatically.
2. **Accepted 24/36 topic coverage as genuinely accurate, not a gap to force-fill.** Researched and confirmed the remaining 12 topics (osteoarthritis, rheumatoid arthritis, osteoporosis, chronic kidney disease, lung cancer, peptic ulcer disease, irritable bowel syndrome, arrhythmia, hypothyroidism, hyperthyroidism, migraine, Parkinson's disease) have no dedicated WHO guideline — WHO focuses guideline-writing on conditions with global/low-resource-country public health impact, leaving other conditions to specialty medical societies (ACR, KDIGO, ATA, IHS, etc.).
3. **Decided against adding a 4th specialty-society source** for the 12 gap topics. Locked a clearer underlying design principle instead: each of the three sources answers a distinct question (PubMed = what does research show, OpenFDA = what does the FDA label say, WHO = what are the official global health recommendations), and the RAG system should honestly state when WHO guidance doesn't exist for a topic rather than fabricating it or silently blending it with the other two sources.
4. **Shared documents mapped across related topics** — several WHO documents legitimately cover multiple project topics at once (e.g., the PEN package for asthma + COPD; the CVD risk guideline for coronary artery disease + heart failure + stroke + hyperlipidemia; mhGAP for depression + anxiety disorder + epilepsy), so 17 unique documents cover the 24 mapped topics.
5. **Store full extracted text at ingestion, no chunking yet** — same boundary as PubMed/OpenFDA; chunking is deferred to Phase 6.

## Results

- **24 of 36 topics** successfully ingested (17 unique source documents).
- **23/24 succeeded on the first production batch run**; the 1 failure (typhoid) was fixed by correcting its URL to the right format, reaching **24/24** on retry.
- Full extraction verified clean and readable across documents ranging from 14 to 451 pages.

## Challenges & Solutions

- **WHO's IRIS repository migrated to a JavaScript-based DSpace 7 frontend**, which broke every old-style `apps.who.int/iris/bitstream/handle/...` URL — these now return the JS app shell instead of the file, since `requests` can't execute JavaScript to follow the client-side redirect a browser performs invisibly.
  - **Solution:** discovered and used IRIS's underlying DSpace REST API to resolve a document's permanent handle to its actual downloadable bitstream, through a 3-step chain (handle → item → bundle → bitstream). This is unofficial/reverse-engineered, not documented by WHO — a known risk flagged for any future re-run if WHO changes their API again, though it doesn't affect the 24 documents already ingested.
- **403 Forbidden on direct downloads** — WHO's servers reject requests without a browser-like `User-Agent` header. Solved by sending a standard Chrome user-agent string with every request.
- **No public search API for WHO content at all** — unlike PubMed/OpenFDA, source discovery had to be done manually per topic via web search, accepting that some topics would have no dedicated WHO guideline rather than forcing coverage.
- **One URL in the initially curated list used the old download format even after resolution** (typhoid) — caused a `PdfStreamError` on first batch run; fixed by correcting it to the standard `bitstreams/{uuid}/content` pattern.

## Files Created

- `notebooks/phase04_who_guidelines.ipynb`
- `backend/src/medrag/ingestion/who_client.py`
- `backend/src/medrag/ingestion/models.py` (updated — added `Guideline`)
- `backend/src/medrag/ingestion/storage.py` (updated — added `save_guideline`, `load_guideline`, `load_drugs`)
- `backend/scripts/run_who_ingestion.py`
- `data/raw/who/*.json` (24 files, some topics sharing the same underlying document content)
- `docs/phase04_report.md`