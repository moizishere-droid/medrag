# Phase 5: Text Chunking — Report

## Phase Objective

Split all ingested content (PubMed articles, OpenFDA drug records, WHO guideline text and tables) into embedding-ready chunks, using a source-aware strategy chosen through rigorous, evidence-based testing of multiple chunking techniques — rather than assuming one universal approach would work equally well across three structurally different data sources.

## What Was Built

- **`Chunk` data model** (`processing/models.py`) — `text` (contextually prefixed, used for embedding), `raw_text` (original unprefixed content, for display/citation), plus `source`, `topic`, `source_id`, `chunk_index`, `chunk_type` (`"text"` or `"table"`), and `metadata`.
- **spaCy-based sentence chunker** (`processing/chunker.py`):
  - A shared pipeline (`get_spacy_pipeline()`) using spaCy's rule-based `sentencizer` (not the statistical parser, which refuses manual sentence-boundary overrides) plus a custom `fix_abbreviation_boundaries` component that prevents incorrect splits after common medical/scientific abbreviations (Fig., e.g., vs., mg., Dr., et al., etc.).
  - `sentence_based_chunk()` — groups spaCy-detected sentences into target-token-sized chunks without ever cutting a sentence mid-way.
- **Per-source chunking functions:**
  - `chunk_pubmed_article()` — abstracts chunked at a 500-token target (most stay as one chunk; a genuine minority split cleanly).
  - `chunk_openfda_drug()` — field-by-field chunking (indications, dosage, contraindications, warnings, adverse reactions, interactions, mechanism of action), with long fields sub-split via the same sentence-based chunker.
  - `chunk_who_guideline()` — `clean_text` chunked via sentence-based chunking (300-token target); each extracted table kept as one atomic chunk, never split.
- **Contextual chunk prefixing** — every chunk's `text` is prefixed with its source context (article title / `"{brand_name} — {field label}"` / guideline title) before embedding, so an isolated sub-chunk from a long field or document remains self-contained and semantically complete on its own.
- **Storage** (`processing/storage.py`) — `save_chunks`/`load_chunks`, one JSONL file per topic per source under `data/processed/chunks/{pubmed,openfda,who}/`.
- **Runner script** (`run_chunking.py`) — processes all 36 PubMed topics, 36 OpenFDA topics, and 24 WHO topics in one batch.

## Key Design Decisions

A total of **six chunking techniques** were tested on real sample documents (primarily the WHO hypertension guideline, the longest and most structurally complex source) before deciding the final strategy — each rejected or accepted with concrete evidence, not assumption:

| Technique | Result | Verdict |
|---|---|---|
| Fixed-size | 110 chunks, cuts mid-sentence | Rejected — arbitrary boundaries break meaning |
| Sentence-based (naive regex) | 117 chunks, clean boundaries | Superseded — mishandles medical abbreviations (confirmed with a direct "Fig. 3" test case) |
| Recursive/paragraph-based | Identical output to sentence-based | Rejected — no real paragraph breaks (blank lines) survived `pdfplumber` text extraction |
| Sliding window (with overlap) | 174 chunks, overlap confirmed working | Not chosen for the default — ~1.5x more chunks for boundary-safety benefit; noted as a candidate to revisit if Phase 18 evaluation shows retrieval missing boundary-spanning facts |
| Semantic (embedding similarity, threshold 0.5) | 474 chunks, over-fragmented (avg. 289 chars) | Rejected — threshold far too aggressive |
| Semantic (threshold 0.3) | 128 chunks, reasonable | Rejected — required fragile, dataset-specific manual tuning with no clear advantage over sentence-based |
| Section-header-based (splitting by the document's own numbered headers, e.g. "5.1 Hypoglycemia") | Excellent on hypertension/malaria/typhoid; unreliable elsewhere | Rejected — false-positive-inflated counts on breast cancer (a street address matched the header pattern) and anemia in pregnancy (repeated title lines miscounted as distinct headers), near-zero detection on mhGAP-based documents (depression/anxiety/epilepsy) and TB/COVID-19; a safe adaptive threshold would need non-trivial extra validation logic (uniqueness, sequential ordering, distribution checks) not justified by the benefit |
| **Sentence-based chunking, spaCy `sentencizer` + custom abbreviation fix** | 113 chunks on the test document, clean boundaries, correct abbreviation handling, generalizes across all tested document types | **Chosen** — the only technique that was both correct and reliably generalizable |

Additional decisions:

1. **spaCy's statistical parser was explicitly avoided** in favor of the rule-based `sentencizer` — the parser recalculates its own sentence starts and raises a `ValueError` (E043) if a manual override is attempted, making it incompatible with the custom abbreviation fix this project needed.
2. **Tables are never split** — each extracted WHO table becomes exactly one chunk (`chunk_type="table"`), preserving row/column meaning that would otherwise be destroyed by any text-based chunking rule.
3. **Images are not chunked at all** — they pass through unchanged to Phase 8's separate CLIP-based image embedding pipeline.
4. **Contextual prefixing was added after testing revealed a real gap**: OpenFDA fields in particular split into many sub-chunks (e.g., a single drug's `adverse_reactions` field split into 8+ pieces), and an isolated sub-chunk's raw text often had no visible mention of which drug or field it belonged to — weakening its embedding similarity to explicit queries (e.g. "what are Glimepiride's warnings"). Prefixing each chunk's embedded text with its source context (while preserving the original in `raw_text`) addresses this directly.

## Results

- **22,688 total chunks** generated across all three sources (true final, after the Phase 3 OpenFDA data correction and all three cross-topic dedup fixes):
  - PubMed: 4,725 chunks (4,159 unique articles — ~10% of articles, 425 PMIDs, genuinely span multiple topics, e.g. anxiety-depression comorbidity papers or anemia-in-pregnancy papers also covering malaria/malnutrition; deduplicated the same way as WHO/OpenFDA rather than storing/embedding each shared article once per topic)
  - OpenFDA: 13,167 unique chunks (467 unique drugs) — deduplicated the same way as WHO: a drug genuinely shared across topics (e.g. naproxen across osteoarthritis, rheumatoid arthritis, etc.) is chunked once and tagged with every topic it belongs to, rather than being duplicated per topic
  - WHO: 4,796 unique chunks across 24 topic files (24 guideline documents, including ~1,204 table chunks alongside sentence-based text chunks)
- Verified correct abbreviation handling with a direct before/after test: `"...compared in Fig. 3 of the study."` stayed intact as one sentence, versus an earlier broken attempt that split it into `"...in Fig."` and `"3 of the study."`
- Verified sliding-window overlap worked correctly (a boundary-spanning sentence was confirmed present in both neighboring chunks) even though it wasn't chosen as the default.
- `dengue fever` and `anemia in pregnancy` correctly show 0 OpenFDA chunks — confirmed as a genuine data limitation (see `docs/phase03_report.md`), not a chunking bug; both topics still have full PubMed and WHO content.

## Note: OpenFDA Source Data Was Corrected Mid-Phase

Between this phase's original run and its final numbers above, a review (documented in `docs/phase03_report.md`) found and fixed a real accuracy bug in Phase 3's OpenFDA matching logic — exact-phrase search matching was added, removing false-positive drug-topic associations (e.g. a diabetes drug incorrectly filed under irritable bowel syndrome), followed by two targeted search-term corrections (`hiv aids`, `peptic ulcer disease`) for topics whose project label didn't match real FDA wording. `run_chunking.py` was re-run against the corrected data to produce the final totals above. PubMed and WHO numbers were unaffected throughout (Phase 3's fix only touched OpenFDA data).

## Final Review: Four Issues Found and Fixed

A deliberate end-to-end review of the whole phase, done before moving to Phase 7, caught four real issues — the same cross-topic duplication pattern turned out to affect all three sources, discovered and fixed one at a time:

1. **WHO shared-document duplication.** Topics sharing one underlying document (asthma/copd via the PEN package; coronary artery disease/heart failure/stroke/hyperlipidemia via the CVD risk guideline; depression/anxiety disorder/epilepsy via mhGAP) were each being chunked independently, producing ~24% exact content duplicates (6,336 chunks where only 4,796 were actually unique) — wasting future embedding cost (Phase 7) and risking near-duplicate results crowding out genuinely different content in retrieval (Phase 9/11).
2. **OpenFDA cross-topic drug duplication (found later, fixed separately).** The same review that caught the WHO issue also surfaced that individual drugs can legitimately (or via residual imprecise matching) appear under multiple topics — e.g. `naproxen` under 13 topics, `prednisone` under 4 — but unlike WHO, this was initially only diagnosed, not fixed in code. Applying it required a different mechanism than WHO's fixed URL groupings, since OpenFDA's cross-topic sharing isn't known upfront: `chunk_openfda()` now scans all loaded drugs across every topic first, groups by `brand_name`, chunks each unique drug exactly once, and saves the result under every topic file it belongs to. Confirmed on real data: OpenFDA dropped from 18,205 to **13,167 unique chunks** (467 unique drugs).
3. **`chunk_id` strings are not valid Qdrant point IDs.** Qdrant (Phase 9) requires point IDs to be an unsigned integer or a UUID, not an arbitrary string like `"diabetes_pubmed_12345678_0"`.
4. **PubMed had the same cross-topic duplication as OpenFDA (checked after fixing OpenFDA's).** 425 of 4,159 unique PMIDs (~10%) genuinely appear under multiple topics — judged as real scientific overlap (comorbidity papers, co-occurring conditions), not a search-matching bug. Fixed the same way: `chunk_pubmed_article()` now requires a `topics` list, `chunk_id` changed from topic-prefixed to `pmid`-based, and `chunk_pubmed()` discovers cross-topic sharing by scanning all loaded articles first. Confirmed on real data: PubMed dropped from 5,391 to **4,725 unique chunks** (4,159 unique articles).

**All four were fixed directly in Phase 6** rather than deferred:
- The `Chunk` model changed from a single `topic: str` field to `topics: List[str]`, so a shared document's or drug's chunks list every topic that references it once, instead of being duplicated per topic.
- A new `point_id` field holds a deterministic UUID5 derived from `chunk_id` (`Chunk.make_point_id()`), generated at chunk-creation time — ready for direct use in Phase 9 without any later rework.
- `chunk_who_guideline()` accepts the full `topics` list for a shared document and uses a canonical id (topics joined with `"+"`, e.g. `"asthma+copd"`) for both `chunk_id` and `source_id`; `chunk_openfda_drug()` similarly requires a `topics` list built by the caller.
- The runner script (`run_chunking.py`) groups WHO shared documents (`WHO_TOPIC_GROUPS`, known upfront) and discovers OpenFDA's cross-topic drug sharing dynamically (by scanning all loaded drugs first, since which drugs are shared isn't known in advance) — both are chunked exactly once and saved under every topic file they belong to.
- `chunk_who_guideline()`, `chunk_openfda_drug()`, and `chunk_pubmed_article()` all now require a `topics` list built by the caller; WHO's shared documents are known upfront (`WHO_TOPIC_GROUPS`), while OpenFDA's and PubMed's cross-topic sharing is discovered dynamically by scanning all loaded records first and grouping by `brand_name`/`pmid` respectively.
- Re-running the full batch confirmed all three fixes: WHO dropped from 6,336 to **4,796 unique chunks**; OpenFDA dropped from 18,205 to **13,167 unique chunks**; PubMed dropped from 5,391 to **4,725 unique chunks**.

## Challenges & Solutions

- **spaCy tokenizes some abbreviations inconsistently** — e.g. `"e.g."` stays as one token, but `"Fig."` is split into `"Fig"` and `"."` as two separate tokens. An abbreviation-matching fix that worked for one case silently failed for the other. Solved by normalizing abbreviation comparison (stripping trailing periods) and correctly offsetting which token's sentence-boundary flag to unset when the period is tokenized separately.
- **The malaria document's `clean_text` (~1.18M characters, 451 pages) exceeded spaCy's default 1,000,000-character safety limit**, crashing the batch mid-run. Solved by excluding the memory-heavy `parser` and `ner` pipeline components (neither is needed for sentence splitting) and raising `nlp.max_length` accordingly, since the limit exists specifically to guard against those components' memory cost.
- **Section-header detection produced misleadingly high counts on some documents** — a street address and repeated document title lines both matched the numbered-header regex pattern without being real headers. This was caught by inspecting the *content* of matches, not just counting them, which is what ultimately ruled out section-based chunking as a safe universal strategy.

## Files Created

- `notebooks/phase06_chunking.ipynb`
- `backend/src/medrag/processing/models.py` (`Chunk` — including `topics: List[str]` and `point_id`)
- `backend/src/medrag/processing/chunker.py` (spaCy pipeline, `sentence_based_chunk`, per-source chunking functions, `_build_chunk`/`Chunk.make_point_id` for deterministic IDs)
- `backend/src/medrag/processing/storage.py` (`save_chunks`/`load_chunks`)
- `backend/scripts/run_chunking.py` (including `WHO_TOPIC_GROUPS` for shared-document dedup)
- `data/processed/chunks/pubmed/*.jsonl` (36 files, 4,725 unique chunks across 4,159 unique articles)
- `data/processed/chunks/openfda/*.jsonl` (36 files, 13,167 unique chunks across 467 unique drugs)
- `data/processed/chunks/who/*.jsonl` (24 files, 4,796 unique chunks, shared correctly across topic groups)
- `docs/phase06_report.md`