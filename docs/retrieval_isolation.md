# Retrieval isolation contract

`hybrid_search()` and `search_with_reranking()` default to curated content
only: source must be `pubmed`, `openfda`, or `who`, and `user_id` must be
empty/missing. A legacy upload missing its ownership field is not curated.
Passing an exact `user_id` adds only that key's uploads. Both dense and sparse
queries receive the same filter, before fusion and reranking. Points marked
`upload_ready=False` are excluded in every mode.

The current API passes the authorized session ID as the retrieval `user_id`;
the upload writer stores the same session ID in that payload field. Thus API
uploads are currently isolated by session, rather than shared across an
account's sessions. Retrieval does not authenticate IDs; endpoints must first
authorize the session. Existing upload staging, registry commit, publication,
and cleanup behavior is preserved.

Trusted internal callers can pass the keyword-only
`full_corpus_evaluation=True` to include all users' published uploads and the
curated corpus. It cannot be combined with a non-None `user_id` and accepts only
a boolean. Never expose this opt-in as a client-controlled endpoint field.
This mode intentionally bypasses ownership isolation; use it only on data
approved for internal evaluation. Legacy points without an `upload_ready`
field remain eligible for compatibility; explicitly staged points do not.

## Call sites

- `backend/scripts/run_evaluation.py`: curated-only by default; explicitly use
  `--full-corpus-evaluation` when the evaluation requires all users' uploads.
  The output records the selected mode.
- `run_pipeline_on_test_set()`: pass `full_corpus_evaluation=True` for that same
  internal use; it forwards the mode to `search_with_reranking()`.
- Direct calls to `hybrid_search()` or `search_with_reranking()` must pass the
  explicit mode if they previously relied on omitted/None IDs to search uploads.
- Notebook 17's RAGAS retrieval call and the imported retrieval calls in notebooks
  11, 14, 15, and 16 now remain curated-only unless deliberately opted in. Their
  curated-corpus examples need no change. Notebook 10's historical helper and
  direct queries also use `build_user_filter(None)` and stay curated-only.
- `/chat`, chat memory, and answer generation retain scoped/default retrieval;
  no evaluation bypass is exposed through their request models.

Regression tests cover omitted and explicit None IDs, exact user scoping,
legacy ownerless uploads, both retrieval signals, evaluation mode, staged
uploads, wrapper forwarding, and the actual upload writer's payload.
