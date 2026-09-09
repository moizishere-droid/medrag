# Phase 9: BM25 Sparse Retrieval — Report

## Phase Objective

Add BM25-based sparse (keyword) retrieval alongside the existing dense (semantic) retrieval built in Phases 6-8, so the system can find exact-term matches — drug names, dosage figures, acronyms — that dense embeddings alone can under-weight. This phase establishes sparse retrieval as a first-class, independently queryable capability inside the existing `medrag_text` collection, setting up Phase 10's RRF (Reciprocal Rank Fusion) to combine both signals.

## What Was Built

- **Hybrid `medrag_text` schema** — migrated from a single unnamed dense vector per point to two named vectors per point: `"dense"` (1536-dim, `text-embedding-3-small`, cosine — unchanged from Phase 8) and `"sparse"` (BM25, IDF-modified, via fastembed's `Qdrant/bm25` encoder).
- **`get_sparse_model()`** (`qdrant_ingestion.py`) — cached loader for fastembed's `SparseTextEmbedding("Qdrant/bm25")`, computed locally, no external API cost.
- **Updated `build_text_point()`** — now attaches both dense and sparse vectors to every point under their named-vector keys, alongside the unchanged payload structure from Phase 8.
- **Updated `upload_source_chunks()`** — computes sparse vectors per upload batch (not per individual point), matching the efficiency pattern already used for embedding batches in Phase 6.
- **Updated `ensure_collections()` / `reset_collections()`** (`qdrant_client.py`) — `medrag_text` is now created with `vectors_config` (dense) and `sparse_vectors_config` (sparse, IDF-modified) together; `medrag_images` is unaffected, since images have no sparse/keyword counterpart.
- All three Phase 8 production files (`qdrant_client.py`, `qdrant_ingestion.py`, `run_qdrant_ingestion.py`) were updated in place to reflect the new hybrid schema, rather than duplicated into new files — the old dense-only schema is now obsolete, not an alternative to preserve.

## Key Design Decisions

1. **Qdrant-native sparse vectors, not a separate library/service.** BM25 was implemented as a named sparse vector living directly inside the same `medrag_text` points as the dense vector, rather than via a standalone Python BM25 library (e.g. `rank_bm25`) or an external search engine (e.g. Elasticsearch). This keeps both retrieval signals in one collection, queryable with a single client, and sets up Phase 10's RRF fusion naturally — no need to synchronize two separate indexes or merge results across systems.
2. **fastembed's `Qdrant/bm25` encoder over a hand-built term/IDF implementation.** Rolling a custom BM25 implementation would mean building and maintaining a vocabulary hashing scheme and IDF computation ourselves; fastembed provides a maintained, purpose-built encoder designed specifically for Qdrant's sparse vector format.
3. **IDF weighting delegated to Qdrant's `Modifier.IDF`, not computed by fastembed.** fastembed's local encoder only computes the term-frequency half of BM25 per document — it has no visibility into corpus-wide term rarity. Qdrant computes and applies the IDF component at query time once the full corpus is indexed, which is the correct architectural split: the encoder doesn't need to know about the whole corpus, only the collection needs to.
4. **`medrag_text` required a genuine collection recreation, not an in-place migration.** Qdrant fixes a collection's vector schema at creation time; adding a named sparse vector to an existing single-unnamed-dense-vector collection isn't possible. This is exactly the case `reset_collections()` (built in Phase 8 specifically for deliberate, opt-in destructive rebuilds) was designed for — used here for a genuine schema change rather than clearing stale test data.
5. **Sparse vectors computed per upload batch, not per point.** Calling the BM25 encoder once per batch of chunk texts (matching Phase 6's batching pattern) is far more efficient than invoking it once per individual chunk across all 22,696 points.
6. **`medrag_images` deliberately untouched.** Sparse/BM25 retrieval only makes sense for text; images keep their original single unnamed CLIP dense vector from Phase 7/8, with no sparse counterpart added.
7. **Existing production files updated in place, not duplicated.** Since the Phase 8 dense-only schema is now obsolete (superseded, not an alternative deployment option), `qdrant_client.py`/`qdrant_ingestion.py`/`run_qdrant_ingestion.py` were revised directly rather than creating parallel Phase 9-specific files — consistent with how the Phase 4 WHO extraction revision was handled.

## Results

- **22,696 text points re-uploaded** with both dense and sparse vectors, matching the exact total from Phase 8 (WHO 4,804 + PubMed 4,725 + OpenFDA 13,167) — server-side `count(exact=True)` verified.
- **76 image points uploaded**, unaffected by the hybrid migration — matching Phase 7/8's confirmed image count.
- **Both vector types confirmed working correctly and independently** in the same collection via separate `using="dense"`/`using="sparse"` queries: dense search returns a self-match at `score=1.0000` (identical to Phase 8's behavior); sparse search on a keyword query ("tuberculosis treatment guidelines") returned only tuberculosis-topic chunks.
- **Corpus-wide IDF weighting confirmed functioning correctly at full scale.** A sparse query for `"metformin diabetes dosage"` against the full 22,696-point corpus returned exclusively relevant OpenFDA metformin/combination-drug chunks (Synjardy, Jardiance, Metformin Hydrochloride, ZITUVIMET), with scores in the ~25-28 range — sharply higher than the ~0.4 range seen on the small 10-point test batch, since IDF's rarity signal only becomes statistically meaningful once the real corpus is fully indexed rather than a handful of test points.
- Production script (`run_qdrant_ingestion.py`) re-run confirmed to reproduce the notebook's exact hybrid result: 22,696 text points (dense + sparse) and 76 image points.

## Challenges & Solutions

- **`AttributeError: module 'qdrant_client.http.models.models' has no attribute 'Modifier'`** — the installed `qdrant-client==1.9.1` predated the IDF modifier feature entirely, while the Qdrant server itself (1.19.0) fully supported it. Resolved by upgrading `qdrant-client` to a current version and updating `backend/requirements.txt` to match, avoiding a client/server version mismatch on any future re-run.
- **Understanding fastembed's flat per-document term-frequency output** required checking the actual output on real text before building anything further: identical weights across every term in a single short test sentence initially looked like a bug, but is expected — fastembed's local BM25 encoder only computes term frequency, and the missing IDF (rarity) component is intentionally supplied by Qdrant's collection-level `Modifier.IDF` at query time, not by the encoder itself. Confirmed correct once real corpus-wide scores (the metformin query) showed properly differentiated, much higher scores than the small-batch test.

## Files Created / Modified

- `backend/src/medrag/embeddings/qdrant_client.py` (modified — hybrid `medrag_text` schema in `ensure_collections`/`reset_collections`, added `DENSE_VECTOR_NAME`/`SPARSE_VECTOR_NAME`)
- `backend/src/medrag/embeddings/qdrant_ingestion.py` (modified — added `get_sparse_model`, updated `build_text_point` and `upload_source_chunks` for hybrid vectors)
- `backend/scripts/run_qdrant_ingestion.py` (modified — docstring updated re: `--reset` required to migrate off the old Phase 8 schema)
- `backend/requirements.txt` (modified — `qdrant-client` version upgraded)
- `notebooks/phase09_bm25_retrieval.ipynb`
- Qdrant collection `medrag_text` recreated with hybrid dense+sparse schema (22,696 points); `medrag_images` unchanged (76 points)