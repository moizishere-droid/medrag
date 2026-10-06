# Phase 21: Testing and final engineering review

Follow-up: see [chat UI, persistent login and topic titles](phase21_ui_followup.md)
for the latest changes, browser evidence, 298 default-suite tests and 49
integration tests. The totals below describe the original audit snapshot.

Date: 6 October 2026. Status: engineering verification complete for the current
local checkout; ready to start Phase 22 (GitHub Actions CI/CD). Deployment
platform selection remains deferred. This report supersedes older test totals
and remaining-work statements in the historical phase reports.

## Scope and evidence

The repository inventory reads every project-owned file, excluding credentials,
Git internals, installed packages, caches, generated audit outputs, and live
database storage. It validates every saved JSON/JSONL record, notebook Python
cell, PDF page, PNG, vector array/index pair, deterministic chunk ID and image
link. It also checks all curated embedding inputs for empty text and the
8,191-token limit. See [the per-file inventory](audit/inventory.json).

Source review covered ingestion, chunking, text/image embeddings, database
ingestion, retrieval, reranking, NER, graph enrichment, generation, citations,
memory, authentication, uploads, the API, frontend, runners and configuration.
All production modules and runner files have an offline import smoke check.
Notebook syntax, saved errors and sensitive retrieval/reset operations were
checked; notebooks were not executed end to end.

## Phase-by-phase result

| Phase | Current verification and disposition |
| --- | --- |
| 00 Architecture | Code and documentation reconciled. The chat path uses retrieved text; CLIP/image storage does not imply multimodal answer generation. |
| 01 Environment | Installed requirements pass `pip check`; Python 3.11.9. Removed duplicate HTTPX declaration, pinned installed test tools, and pinned database image digests to the locally tested images. A clean Linux install remains a Phase 22 check. |
| 02 PubMed | Tested English search filtering, missing language/date fields, collective authors, target-count idempotency and skipping/capping new PMIDs. All saved records structurally validated. |
| 03 OpenFDA | Tested exact quoted search, true no-results handling, parser/dedup behavior and failed-refresh preservation. Runner now fails visibly when a topic fetch fails. |
| 04 WHO | Tested URL-resolution traversal, actual PDF text extraction, figure-page rasterization and repeated/blank image filtering. Inventory parses all saved PDF pages. Failed refreshes now return failure. |
| 05 Chunking | Existing sentence/abbreviation, table splitting and Unicode preservation regressions pass. All saved unique chunk inputs pass the embedding token limit. |
| 06 Text embeddings | Response ordering/count regressions and vector/index save/load corruption checks pass. No fresh paid embeddings generated. |
| 07 Image embeddings/linking | Fixed empty output shape and resource closure; tested image save/load and ordinal linking. Mismatched image/topic lists now fail instead of truncating silently. CLIP inference itself was not rerun. |
| 08 Qdrant | Tested non-destructive collection creation and idempotent curated ingestion in local Qdrant. Runner now respects configured Qdrant URL. Existing live data was not reset/reindexed. |
| 09 BM25 | Tested sparse response-count validation, named vector ingestion and both retrieval signals. Encoders are mocked in offline retrieval tests. |
| 10 Hybrid retrieval | Real-server tests cover omitted/None IDs, exact ownership, malformed legacy uploads, staged points, actual upload payloads and explicit full-corpus evaluation. Both query legs share the filter. |
| 11 Reranking | Wrapper tests verify scope forwarding; candidate narrowing and empty results remain supported. Actual model inference was not rerun. |
| 12 NER | Existing unit checks and the installed real-model extraction smoke test pass. Ambiguous entity/noise limitations remain. |
| 13 Knowledge graph | Extraction rejects non-OpenFDA chunks; graph writes now validate relationship types and batch sizes before connecting. Failed driver setup closes resources. Live graph checks remain read-only. |
| 14 Generation | Prompt/context, source-evidence identity, drug matching and graph constraints pass. Fixed cache reuse across different graph drivers. OpenAI is mocked. |
| 15 Citations | Source display, marker bounds, WHO lookup caching and upload citations pass. OpenFDA public-label URLs remain unavailable in current raw data. |
| 16 Memory | Real PostgreSQL checks cover schema idempotency, ordering, history windows, pool behavior, same-session serialization and complete-turn rollback on citation failure. |
| 17 Evaluation | Tests preserve exact retrieval evidence through generation and forward explicit evaluation mode. Historical RAGAS scores were not regenerated. |
| 18 API/security | Authenticated account/session ownership, forged/expired/revoked tokens, shared rate limits, route validation, worker-thread behavior, pool exhaustion and lifespan cleanup pass. Added remote-client rejection regression for local-only mode. |
| 19 Uploads | Actual Qdrant write/read isolation and PostgreSQL/Qdrant failure recovery pass: staged points stay hidden, duplicate upload retries avoid reembedding, publication failures recover. Manual verification scripts now support tokens, portable paths and safe import guards. |
| 20 Frontend | Streamlit AppTest verifies switching duplicate-title sessions loads the correct history and changes the upload widget identity. Fixed cross-session reuse of a selected PDF; logout clears upload widgets. Backend URL is configurable through `MEDRAG_API_URL`. |
| 21 Testing | Expanded regression coverage, preserved pre-existing local changes, refreshed reports and saved machine-readable test results for the next phase. |

## Corrections in this review

- Session-specific upload widget keys prevent an already selected PDF being
  indexed into a different chat after switching sessions.
- Drug-name caches are scoped to the graph driver. A prior test explicitly
  expected stale data from another graph; it now verifies the correct behavior.
- Graph writers reject unsupported relationship types before interpolating them
  into Cypher, reject nonpositive batch sizes, and enforce OpenFDA extraction.
- Empty image datasets produce `(0, 512)` arrays; image resources close; image
  and topic counts are checked before linking.
- Failed source refreshes preserve prior files and signal failure to jobs.
- Verification scripts no longer connect or issue paid requests merely on
  import, and private endpoints require an explicit existing token.
- Compose pins all three tested image digests; no services/data were replaced.
- Artifact auditing now fails its process when integrity defects are found.
- README and the old audit's security/recovery limitations are reconciled with
  implemented and tested code.

The retrieval privacy fix is detailed in [the isolation contract](retrieval_isolation.md):
missing keys retrieve curated-only content, explicit keys add their own uploads,
and trusted internal full-corpus evaluation must opt in explicitly. The API
continues using authorized session IDs as upload isolation keys.

## Validation

The final combined run passed **317 tests** (272 default tests and 45 integration
tests), with **88% package statement coverage**, no failures, skips or expected
failures. The API's actual lifespan, real dependency health checks and
authenticated session creation passed using the isolated test database.

Final totals and coverage are recorded in [the current audit validation](project_audit_report.md#validation),
[JUnit results](audit/phase21-tests.xml) and [coverage JSON](audit/coverage.json).
The combined suite uses real local PostgreSQL, Qdrant and Neo4j, with OpenAI and
retrieval encoders mocked except the installed NER smoke test. PostgreSQL tests
use `medrag_chat_test`; Qdrant tests create/delete uniquely named collections;
Neo4j integration checks do not write to the graph. No production corpus was
deleted, refreshed or reembedded.

Reproduce from the repository root after installing backend requirements and
the editable package:

```powershell
python -m pytest -q
python -m pytest -m "not live" --cov=medrag --cov-report=term --cov-report=json:docs/audit/coverage.json --junitxml=docs/audit/phase21-tests.xml -q
python backend/scripts/audit_project.py
python -m pip check
docker compose config --quiet
```

For Qdrant-only checks without Docker, set `MEDRAG_TEST_QDRANT_URL=:memory:` and
run `python -m pytest tests/integration/test_qdrant_isolation.py -m integration -q`.
Coverage measures the `medrag` package; the Streamlit test runs separately within
the same suite. Statements not covered by tests remain visible in the coverage
artifact; coverage is not proof of all possible behavior.

## Phase 22 handoff and deployment limits

GitHub Actions should run unit/API/frontend tests with placeholder credentials,
then isolated database integration tests, and publish JUnit/coverage artifacts.
The current Neo4j tests expect an already populated graph: a fresh CI service
will need a dedicated deterministic graph seed or a separate seeded-graph job.
CI must verify a clean Python 3.11 dependency install on Linux; the current
passing environment is an existing Windows installation. Large saved artifacts
can be audited in a separate job. `.github/workflows` currently contains only
its placeholder; workflows are the next phase, not implemented by this review.

Public deployment still needs the chosen platform's TLS, secret injection,
network restrictions for database ports, persistent storage/backups, startup
and readiness checks, resource limits, and authenticated production settings.
The local Compose development credentials/ports are not a production hosting
configuration. Historical unowned sessions are not automatically assigned to
new accounts. Upload visibility remains per session even within one account.

Paid model calls, fresh source downloads, fresh embeddings, full notebook
execution, fresh Linux installation, live browser multipart upload interaction,
and RAGAS rescoring were not performed. OCR, clinical validation of noisy graph
relationships, multimodal chat, caption-link quality and missing-source coverage
are functional/research limits, not resolved by passing software tests. No claim
is made that every possible defect has been eliminated or that the system is
already ready for public medical use.
