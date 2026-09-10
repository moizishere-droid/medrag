# Phase 11: Cross-Encoder Reranking — Report

## Phase Objective

Add a reranking layer on top of Phase 10's hybrid retrieval, using a cross-encoder that scores the query and each candidate chunk *together* rather than comparing independently-encoded vectors. This directly addresses the weak-result pattern surfaced by Phase 10's diagnostic query, where dense and sparse retrieval each scored chunks in isolation and let a topically-adjacent but substantively irrelevant chunk (a bibliography entry) rank highly.

## What Was Built

- **`get_cross_encoder()`** — cached loader for `cross-encoder/ms-marco-MiniLM-L-6-v2` via `sentence-transformers`.
- **`rerank()`** — scores a list of `hybrid_search()`-shaped candidates against a query text using the cross-encoder, returning the top-N sorted by the new score.
- **`search_with_reranking()`** — the full two-stage pipeline: calls `hybrid_search()` (Phase 10) for a wider candidate pool, then `rerank()` to narrow it to a smaller, more precisely relevant result set.
- **`backend/src/medrag/retrieval/reranking.py`** — added to the existing `medrag.retrieval` package alongside Phase 10's `hybrid_search.py`.

## Key Design Decisions

1. **Reranking as a second pass over a retrieval-narrowed pool, never a replacement for retrieval.** A cross-encoder can't be precomputed or indexed — its score only exists for a specific (query, chunk) pair, computed at query time — so running it over the full 22,696-chunk corpus per query would be far too slow. `search_with_reranking()` always retrieves a wider pool first (default 20) via the fast bi-encoder methods from Phase 10, then reranks only that pool.
2. **General-purpose `ms-marco-MiniLM-L-6-v2` over a biomedical-specific cross-encoder.** A domain-specific alternative was considered but not used: it would add another model dependency for a modest accuracy gain, and the project already has scispaCy scoped separately (Phase 12) to handle medical-term precision. The general-purpose model is also the more standard, well-established choice for demonstrating reranking mechanics.
3. **`candidate_pool_size` kept meaningfully larger than `top_n`.** Reranking is only useful if it has room to promote a chunk that retrieval's own top-N missed — retrieving exactly N candidates and reranking that same N would give the cross-encoder nothing new to surface. Documented explicitly in the function's docstring as a usage constraint, not just a default value.
4. **No attempt to normalize or bound the cross-encoder's raw scores.** `ms-marco-MiniLM` outputs a raw logit, not a probability or cosine-style bounded value — negative scores are normal and don't by themselves indicate irrelevance. Only relative ordering within one query's candidate pool determines final ranking. This is documented plainly rather than papered over with an arbitrary rescaling that would imply false precision.

## Results

- **Directly re-tested Phase 10's diagnostic query** ("how does the body regulate blood sugar") through the full retrieve-then-rerank pipeline: the WHO abbreviations-glossary chunk that had ranked #1 after RRF fusion correctly dropped out of the top 5 entirely once scored against the actual query content. A genuinely relevant chunk (a different sulfonylurea's mechanism-of-action text, explaining insulin release from pancreatic beta cells) that hadn't appeared in hybrid search's original top 5 at all was correctly promoted into the top 5 after reranking — found only because the wider 20-candidate pool gave the cross-encoder a chance to see it.
- **Score magnitude as an informal confidence signal**: the weak diagnostic query topped out at a cross-score of -1.64 even after reranking (best available candidate, still not strongly relevant), while two well-covered test queries topped out strongly positive (+7.55 for a drug-specific query, +6.15 for an adverse-effects query) — consistent with Phase 10's diagnosis that the corpus itself has limited coverage for certain broad conceptual questions, rather than a reranking failure.
- **Confirmed reranking does not degrade an already-good result set.** Re-running the metformin drug query (which hybrid search alone already handled well) through reranking kept all top-5 results genuinely relevant, refining which specific metformin/combination-drug chunks surfaced without introducing any off-topic results.
- **A third, fresh query** ("side effects of ACE inhibitors") returned a direct adverse-effects table as the top result — an exact, precise answer to the question, confirming the pipeline generalizes beyond the two queries used for diagnosis and regression testing.
- **Production `search_with_reranking()` verified to exactly reproduce notebook output**, byte-for-byte, on the ACE inhibitor test query.

## Challenges & Solutions

- No significant implementation obstacles this phase — the main substantive work was validating that reranking genuinely fixes the specific failure mode identified in Phase 10 (rather than just assuming a cross-encoder would help), which required running the exact diagnostic query through before/after comparison and inspecting real `raw_text` content at each stage rather than trusting scores alone.

## Files Created

- `backend/src/medrag/retrieval/reranking.py` (`get_cross_encoder`, `rerank`, `search_with_reranking`)
- `notebooks/phase11_reranking.ipynb`

No new runner script — same reasoning as Phase 10: reranking is a function library called on-demand, not a batch job with a standalone production entry point.