# Phase 6: Text Embeddings — Report

## Phase Objective

Generate dense vector embeddings for every unique chunk produced in the chunking phase, across all three data sources (PubMed, OpenFDA, WHO Guidelines), so the chunks are ready for ingestion into Qdrant in the next phase.

## What Was Built

- A full embedding pipeline, first validated cell-by-cell in `notebooks/phase07_embeddings.ipynb` on real data (819 chunks from the diabetes topic) before being lifted into production code.
- Deduplication by `point_id` prior to embedding, so each unique chunk (even if it appears in multiple topic files on disk) is only embedded once.
- Token/count-aware batching: batches capped at 500 chunks or 250k tokens, whichever limit is hit first.
- Retry-wrapped batch embedding calls to `text-embedding-3-small`.
- Save/load implemented via NumPy `.npy` files (vectors) plus a JSONL index (metadata/point_id mapping), with a confirmed round-trip test.
- Production code lifted to `backend/src/medrag/embeddings/{embedder.py, storage.py}` and `backend/scripts/run_embeddings.py`.

## Key Design Decisions

- **Dedup before embedding, not after**: embedding by unique `point_id` rather than by every on-disk chunk line avoided paying to re-embed the same content multiple times across shared topics (e.g. WHO documents shared across topics, OpenFDA drugs shared across topics).
- **Batching strategy**: dual-limit batching (chunk count *and* token count) rather than a single fixed batch size, to stay safely under API batch limits regardless of how token-dense a given batch of chunks happens to be.
- **Storage format**: NumPy arrays for vectors (fast to load, compact) paired with a JSONL index for metadata, rather than a single combined format — keeps vector loading fast while metadata stays human-readable/inspectable.

## Results

- **PubMed**: embedded successfully on first pass.
- **OpenFDA**: embedded successfully on first pass.
- **WHO**: initially failed on oversized table chunks (some WHO tables, e.g. GRADE evidence tables, contain individual cells long enough to exceed OpenAI's 8,192-token input limit). Fixed via a two-stage splitting approach in `chunker.py` (see Challenges below). After the fix, WHO embedding succeeded.

**Final embedding counts (all sources, deduplicated by `point_id`):**

| Source | Unique embeddings |
|---|---|
| PubMed | 4,725 |
| OpenFDA | 13,167 |
| WHO | 4,804 |
| **Total** | **22,696** |

(WHO's count is slightly higher than its pre-embedding chunk count of 4,796, because the table-splitting fix turned a small number of oversized table chunks into a couple of extra, correctly-sized pieces.)

Estimated embedding cost: ~6.56M unique tokens (deduplicated) at `text-embedding-3-small` pricing, ≈ **$0.13** total.

## Challenges & Solutions

**Challenge**: OpenAI's `text-embedding-3-small` enforces a hard 8,192-token input limit. A subset of WHO table chunks (e.g. long GRADE evidence tables) exceeded this because pdfplumber-extracted table rows were grouped in a way that could still leave an individual oversized cell or row-group too large.

**Solution**: Two-stage splitting in `chunker.py`:
1. `_split_table_by_rows` — groups table rows under a 6,000-token budget per group.
2. `_token_window_fallback_split` — a guaranteed safety net for any group still too large after row-grouping (e.g. a single oversized cell).

A bug was caught and fixed during this work: the fallback splitter initially only re-prepended the chunk's context prefix (title/page/part) to the *first* resulting piece. This was corrected so every resulting piece keeps the full context prefix, preserving self-contained, embeddable chunks throughout.

## Files Created

- `notebooks/phase07_embeddings.ipynb` (exploration/validation notebook)
- `backend/src/medrag/embeddings/embedder.py`
- `backend/src/medrag/embeddings/storage.py`
- `backend/scripts/run_embeddings.py`
- Data outputs: embedding vectors as `.npy` files + JSONL index, per source, saved locally