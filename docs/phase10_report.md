# Phase 10: Hybrid Retrieval (RRF) — Report

## Phase Objective

Combine the dense (semantic) and sparse (BM25 keyword) retrieval signals built in Phases 6-9 into a single fused ranking, using Reciprocal Rank Fusion (RRF), so queries benefit from both signals simultaneously rather than choosing one or the other.

## What Was Built

- **`reciprocal_rank_fusion()`** — hand-implemented RRF: for each ranked result list, every result contributes `1/(k + rank)` to its chunk's running fused score (rank 1-indexed); a chunk appearing in multiple lists accumulates contributions from each.
- **`hybrid_search()`** — the full retrieval function: embeds the query with both the dense model (`text-embedding-3-small`) and the sparse model (fastembed's `Qdrant/bm25`, same encoder used to build the stored sparse vectors in Phase 9), queries `medrag_text`'s `"dense"` and `"sparse"` named vectors independently, then fuses the two ranked lists.
- **`backend/src/medrag/retrieval/`** — new package (`hybrid_search.py` + `__init__.py`), the first module in what will become the project's retrieval layer.

## Key Design Decisions

1. **Client-side hand-implemented RRF (`k=60`) over Qdrant's native prefetch+fusion API.** Both approaches were built and directly compared in the notebook. Qdrant's native `Fusion.RRF` (via the installed client version) turned out to use a fixed, non-configurable `k=1` — verified by manually reconstructing several of its output scores from the underlying rank positions (e.g. a chunk at dense-rank 1 + sparse-rank 3 scored exactly `1/(1+1) + 1/(1+3) = 0.75`, matching Qdrant's output). `k=1` is considerably more aggressive than the standard `k=60` from the original RRF paper — it behaves close to "did this chunk rank #1 anywhere" rather than genuinely blending rank positions across both signals. The hand-implemented version was chosen for production because it uses the well-established convention, is fully tunable, and its behavior is directly understood and explainable (a priority given the project's interview-readiness goal) rather than inherited as an undocumented client default.
2. **Two separate requests (dense + sparse) plus client-side fusion, not a single native round-trip.** This costs one extra network round-trip compared to native fusion, judged an acceptable tradeoff at this project's scale (a portfolio RAG system, not a high-QPS production service) in exchange for correctness and control over `k`.
3. **`per_signal_limit` kept separate from the final `limit` parameter.** The notebook's original version conflated "how many candidates each signal contributes" with "how many final results are returned." The production function separates these deliberately — a wider candidate pool per signal (default 10) generally produces better fusion quality than the narrower pool used during initial notebook testing, and this was confirmed directly: re-running with `per_signal_limit` matched to the notebook's original narrower value reproduced its exact output, isolating the difference as a design choice rather than a bug.
4. **No attempt to filter or "fix" weak results inside fusion.** A diagnostic query ("how does the body regulate blood sugar") surfaced some low-relevance chunks (a bibliography/reference-list entry, incidental BM25 keyword overlap with unrelated drug dosage text). Rather than hand-tuning `k`, filtering chunk types, or otherwise engineering around this inside the fusion logic, it was judged to be exactly the failure mode reranking exists to solve — dense and sparse each score a chunk in isolation, never comparing query and chunk together the way a cross-encoder (Phase 11) does. This is documented here as an honest, expected limitation and the direct motivating example for Phase 11, consistent with the project's established principle of surfacing real limitations rather than papering over them.

## Results

- **Dense-only, sparse-only, and fused results all verified independently** on a real hypertension-related query, confirming both signals function correctly and that fusion correctly promotes chunks that rank well in *both* lists (four chunks appearing in both dense and sparse top-10s took the top four fused positions, each roughly double the score of single-signal-only chunks).
- **A drug-specific query** ("metformin dosage for diabetes") returned exclusively relevant OpenFDA metformin/combination-drug chunks after fusion — confirms sparse's exact-term strength survives fusion for keyword-heavy queries.
- **A broad conceptual query** ("how does the body regulate blood sugar") surfaced some genuinely weak results after fusion (a bibliography entry, an unrelated PubMed abstract, dosage instructions for an unrelated drug) — diagnosed via separate dense-only/sparse-only inspection as a combination of (a) a real corpus-coverage gap (the corpus is guidelines/labels/abstracts, not physiology-textbook content) and (b) the expected score-in-isolation weakness of pure hybrid retrieval without reranking. Documented as a known limitation, not treated as a bug to fix in this phase.
- **Production `hybrid_search()` verified to exactly reproduce notebook output** once `per_signal_limit` was aligned — confirmed byte-for-byte identical fused scores and chunk ordering on the metformin test query.

## Challenges & Solutions

- **Qdrant's native RRF fusion silently used a different `k` than expected**, discovered only by directly comparing native vs. hand-implemented results on the same query rather than assuming the native path was a drop-in equivalent. Resolved by tracing the exact math on several results to confirm `k=1`, then making a deliberate, documented choice to use the hand-implemented version instead.
- **A misleadingly weak result set on a broad conceptual test query** initially looked like it could be a fusion bug. Resolved by decomposing the query into dense-only and sparse-only results with visible `raw_text` snippets, which revealed the weak results were individually explainable (isolated scoring, real coverage gaps) rather than an artifact of the fusion math itself — avoided the mistake of "fixing" fusion logic to paper over a limitation that reranking is meant to address.

## Files Created

- `backend/src/medrag/retrieval/__init__.py`
- `backend/src/medrag/retrieval/hybrid_search.py` (`get_openai_client`, `get_sparse_model`, `embed_query_dense`, `embed_query_sparse`, `reciprocal_rank_fusion`, `hybrid_search`)
- `notebooks/phase10_hybrid_retrieval.ipynb`

No new runner script this phase — unlike ingestion/embedding/upload (one-time batch jobs), retrieval is a function library called on-demand by other code (API endpoints, later phases), not something with a standalone production entry point to run.