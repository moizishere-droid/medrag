# Phase 15: Citation System — Report

## Phase Objective

Turn Phase 14's lightweight bracketed citation markers (`[1]`, `[1][3]`) into structured, resolved citation objects — real source titles, clickable links where available, and linked image references — so a frontend can render clickable, verifiable citations that let a user trace any claim back to its original source (a PubMed paper, WHO guideline, or FDA label).

## What Was Built

- **`build_who_source_url_lookup()`** — reads Phase 4's raw WHO Guideline JSON files directly to recover `source_url`, which was never carried through to `Chunk.metadata` during chunking.
- **`get_who_source_url()`** — resolves a WHO chunk's (possibly multi-topic) `source_id` back to its source URL.
- **`get_display_info()`** — per-source logic for building a citation's display title and URL (or `None` where no stable link exists).
- **`extract_used_citation_numbers()` / `build_citations()`** — parses the generated answer text for markers actually used, and resolves each back to a full structured citation object.
- **`backend/src/medrag/citations/`** — new package (`citations.py`, `__init__.py`).

## Key Design Decisions

1. **Answer text is left completely unmodified; citation data is returned separately.** Rewriting `[1]` into a rendered link, footnote marker, or hover element is a presentation decision that belongs to the frontend (Phase 20, Streamlit). This phase's responsibility ends at producing correct, structured data for that layer to consume however it chooses.
2. **Per-source citation display was investigated against real data before designing a format, not assumed uniform across sources.** Each source's actual available metadata was inspected directly: WHO has a title but its `source_id` is a non-human-readable topic slug; OpenFDA has no title field at all but its `source_id` is the human-readable drug name; PubMed has both a real title and an ID (PMID) that constructs a genuine public URL.
3. **WHO source URLs are recovered from Phase 4's raw ingestion output, not by modifying the chunker.** `Guideline.source_url` existed on the ingestion model all along but was never propagated into `Chunk.metadata` during Phase 5. Rather than touching and re-running the chunking pipeline, a separate lookup reads the original raw JSON files directly — a real, working WHO IRIS link recovered with zero changes to already-validated upstream code.
4. **PubMed gets a real, constructible public URL** (`https://pubmed.ncbi.nlm.nih.gov/{pmid}/`) directly from its stored PMID — no additional data recovery needed.
5. **OpenFDA citations are title-only, with `url=None`, as a deliberate, honestly-documented limitation.** The raw OpenFDA ingestion (Phase 3) never captured any identifier (`set_id`, `application_number`, or similar) that could construct a stable public label URL — confirmed by inspecting the actual raw record fields directly rather than assuming one existed. Reconstructing this would require re-querying OpenFDA's API, out of this phase's scope. The citation still shows a genuinely useful title (drug name + specific label section, e.g. *"Ramipril — FDA Label (Warnings And Cautions)")* even without a clickable link — consistent with the project's established pattern of stating real gaps plainly rather than hiding them.
6. **Only citation markers actually present in the generated text are resolved.** `build_citations()` parses the real answer text for `[N]` markers rather than assuming every retrieved chunk was cited — a chunk retrieved but not referenced by the model produces no citation object.
7. **Out-of-range citation markers are skipped with a warning, not raised as an error.** If a model ever hallucinates a citation number beyond the actual context size, the malformed reference is dropped rather than crashing the whole response — a single bad citation shouldn't take down an otherwise-valid answer.

## Results

- **A real bug was found and fixed during testing**: WHO chunks shared across multiple topics carry a combined `source_id` (e.g. `"coronary artery disease+heart failure+hyperlipidemia+stroke"`, per Phase 5's canonical-ID convention for shared documents), but the initial URL lookup was keyed by single topic filenames — a direct match against the combined string silently failed, returning `url: None` for a WHO citation that should have had one. Fixed by splitting the combined `source_id` on `+` and checking each component topic, since every topic in the group shares the same underlying document and URL.
- **All three source types verified correct after the fix**: a WHO citation resolved to a real, working IRIS URL and correct guideline title; an OpenFDA citation correctly showed a constructed title with no URL; both were confirmed on citations generated from an actual model-produced answer, not synthetic test data.
- **Linked image data (Phase 7/8) confirmed to flow through end-to-end**: tested directly against the known `hypertension_who_text_16` → `hypertension_page2_img0.png` linkage established and manually verified back in Phase 7/8 — the same link, with its own `point_id`, appeared correctly in the final citation object, ready for a frontend to fetch and display alongside the text citation.
- **Production `build_citations()` verified to exactly reproduce the notebook's fixed output** on the same real answer text and retrieval results.

## Challenges & Solutions

- **A real, previously-undiscovered gap was found in Phase 5's chunking output**: `Guideline.source_url` had been captured during Phase 4 ingestion but never made it into `Chunk.metadata`. Rather than treating this as a full defect requiring a chunker fix and a costly re-chunk/re-embed/re-upload cycle across every downstream phase, the citation system reads the original raw ingestion files directly — a targeted, lower-risk fix that doesn't touch or invalidate any already-validated Phase 5-9 work.
- **OpenFDA's missing identifier gap was confirmed, not assumed.** Rather than guessing that no usable link field existed, the actual raw ingested JSON record was inspected directly, confirming its exact field set before deciding title-only display was the right, honest choice for this phase.

## Files Created

- `backend/src/medrag/citations/__init__.py`
- `backend/src/medrag/citations/citations.py` (`build_who_source_url_lookup`, `get_who_source_url`, `get_display_info`, `extract_used_citation_numbers`, `build_citations`)
- `notebooks/phase15_citation_system.ipynb`

No new runner script — citation resolution is a function library invoked per-generated-answer, not a batch job.