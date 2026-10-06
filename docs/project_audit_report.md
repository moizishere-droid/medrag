# MedRAG phase-by-phase audit
Updated 6 October 2026 during [Phase 21](phase21_report.md). This audit covers project-owned source, scripts, configuration, tests, phase reports 00–21, all 17 notebooks, and saved data artifacts. The per-file inventory is in [audit/inventory.json](audit/inventory.json). Credentials, Git internals, installed third-party packages, caches, generated audit outputs, and live database storage directories are excluded. Database behavior is checked through isolated integration tests instead. File inventory/syntax checks and semantic review are distinct; full notebook execution and clinical validation are not claimed.

## Findings and corrections by phase

| Phase | Review and outcome |
| --- | --- |
| 00 — Architecture | Corrected outdated README status and documentation references. The image pipeline exists, but the chat API currently generates from retrieved text; full multimodal chat remains outside the implemented path. |
| 01 — Environment | Installer referenced a deleted frontend requirements file and continued after failures. Fixed working-directory handling and failure checks. Sample database settings now match Compose. Removed unused incompatible experiment-tracking dependency. |
| 02 — PubMed | Added English search filtering; closed Entrez handles; handled empty fetches and missing language/date fields; cleared stale API keys. Storage now deduplicates appended PMIDs. Notebook ingestion uses the production target-count logic. Saved corpus has 4,680 topic rows representing 4,159 distinct PMIDs. |
| 03 — OpenFDA | Request failures no longer masquerade as empty successful results and overwrite saved topics. Runner preserves files on failed requests. Parser handles empty identity arrays. Notebook uses quoted production search and parser. |
| 04 — WHO | Fixed notebook use of undefined `__file__`. PDF extraction resources now close on both success and exceptions. Saved 24 topic documents represent 18 distinct source URLs. |
| 05 — Chunking | Fixed abbreviation boundaries, Unicode token slicing, and token-window prefix budgeting. Pathological long sentences split before embedding limits; invalid token targets fail clearly. Pipeline initialization is serialized. Final notebook helpers use corrected production logic. |
| 06 — Text embeddings | Enforced nonempty inputs and per-input limits; validated response counts/index order; handled empty datasets. Save/load and ingestion reject mismatched or nonfinite vectors. Notebook batching/retries use the production helpers and configured key. |
| 07 — Images | Replaced notebook save-function stub that could write an empty index. Image storage validates vector/record/topic alignment. Saved PNG files and 512-dimensional image vectors pass integrity checks. |
| 08 — Qdrant | Notebook reset operations now target dedicated experiment collections, protecting production collections. Replaced obsolete search calls with the current query API. Production collection management remains non-destructive on normal ingestion. |
| 09 — BM25 | Notebook schema migration now uses a dedicated experiment collection. Sparse response counts and ingestion batch sizes are validated. |
| 10 — Hybrid retrieval | Missing isolation keys now retrieve only curated sources. Untagged legacy uploads are excluded as well. Both dense and sparse queries receive the same filter. Notebook direct queries and final helper apply the corrected filter. |
| 11 — Reranking | Empty candidate lists and nonpositive result counts return safely without model loading. Notebook final reranker uses the corrected implementation. |
| 12 — NER | Dosage detection no longer treats laboratory units such as mg/dL as medication doses. Notebook shares the corrected pattern. |
| 13 — Knowledge graph | Reviewed extraction, aggregation and writes. Relationships inferred from label sections remain noisy candidates; this audit does not establish their medical truth. Generation no longer treats them as verified evidence. |
| 14 — Generation | Drug matching uses word boundaries and the longest matching name. Graph candidates cannot override cited source text. Generation can consume a supplied retrieval result list, preserving evidence identity. Notebook prompt and matching share these fixes. |
| 15 — Citations | WHO source cache respects the input directory; missing/empty IDs and nullable metadata are handled. Notebook display/source lookup uses production helpers. |
| 16 — Memory | Malformed UUIDs return false before reaching PostgreSQL; valid sessions retain existing behavior. Reviewed query reformulation, bounded history, persistence and citation updates. Isolated database tests cover these behaviors. |
| 17 — Evaluation | Removed duplicate retrieval: generation uses the exact contexts scored by evaluation. Notebook pipeline uses the same evidence. Existing saved scores are historical and have not been regenerated. Context-recall uncertainty documented in the original phase remains. |
| 18 — API | Blocking routes run in worker threads, including their database/citation work. Async uploads offload blocking stages. Added UUID/blank-message validation, bounded file reads, pool-exhaustion responses, and resource cleanup after partial startup failure. |
| 19 — Uploads | Upload embeddings are batched and validated. Replaced obsolete notebook isolation experiments with a session-scoped demonstration in a uniquely named temporary collection. Cleanup deletes only that collection. Existing production data was not reset. |
| 20 — Frontend | Added timeout/error handling for session creation and history loading. Failed history fetches preserve the current visible session. Empty health responses cannot report every dependency healthy. |
| 21 — Testing | Added source/PDF/vector/storage/graph/runner/frontend tests and import smoke checks. Fixed cross-session PDF widget reuse, graph-driver cache scoping, graph write validation, image output/alignment/resource handling and refresh failure exit status. Pinned tested database image digests. See the complete [Phase 21 report](phase21_report.md). |

## Validation

The final complete run passed **317 tests**: 272 default unit/API/frontend tests and 45 integration tests against the running local PostgreSQL, Qdrant and Neo4j services. There were no failures, skips or expected failures. Package statement coverage is **88%**, up from 60% at the start of this review. The actual API lifespan, health checks and authenticated session creation also passed against real services with PostgreSQL writes isolated to the test database. See [JUnit results](audit/phase21-tests.xml), [coverage JSON](audit/coverage.json) and the [Phase 21 report](phase21_report.md).

The artifact inventory validates all saved records, notebook code syntax, PDF pages, PNG integrity, vector dimensions/finiteness/index alignment, deterministic point IDs, image links and curated embedding token limits. It reports no artifact-integrity defects. There are 22,696 unique curated text chunks: 4,725 PubMed, 13,167 OpenFDA and 4,804 WHO. All 17 notebooks have no saved error outputs. `pip check` reports no broken installed requirements, and the pinned Compose configuration validates.

PostgreSQL writes use the guarded `medrag_chat_test` database. Qdrant tests use uniquely named temporary collections. Neo4j integration checks are read-only. The Streamlit AppTest and offline imports require no external services; OpenAI/model encoders are mocked except the installed NER smoke test. Production data was not deleted, refreshed, reembedded or rescored. Full notebooks, paid model requests and fresh source downloads were not run. Test coverage measures the `medrag` package, not the frontend or runner statements.

## Previously reported blockers now resolved

- Authentication, account-owned session lists, revocable/expiring tokens and shared rate limits are implemented and tested. Disabling auth permits private routes only for local development clients.
- Database-backed session locks serialize concurrent operations on one chat. Different sessions continue concurrently.
- Chat messages and citations commit atomically; a citation failure rolls back the complete turn.
- Uploads remain hidden while staged. A failed embedding/index operation cleans up; deterministic document IDs and a SQL registry support retries. A failed publication after commit is repaired without reembedding.
- Missing retrieval IDs cannot expose uploads. Full-corpus evaluation is an explicit internal opt-in and still hides staged points.
- Database image tags are replaced with immutable digests from the actual tested local images. Fresh Linux provisioning is still a CI task.

## Remaining limits and next phase

- Clinical truth of automatically extracted graph relationships is not established. Negation, ambiguous entities and source-coverage gaps remain; graph candidates cannot override cited source text.
- General uploads have no OCR path; scanned PDFs without text are rejected. Uploaded PDFs do not use WHO-specific table/layout processing.
- Chat generation uses text contexts. Image embeddings and heuristic figure links do not provide full multimodal chat.
- RAGAS scores are historical; paid rescoring and LLM-as-judge variability remain outside these engineering checks.
- The final checkout has not been installed from scratch on a clean Linux runner. This is a Phase 22 gate. Current Neo4j read-only tests require a populated graph; fresh CI needs a dedicated deterministic seed.
- Account uploads remain scoped to their chat session. Historical unowned sessions are not claimed by newly registered accounts.
- The local Compose defaults are development settings. Deployment requires TLS, platform secrets, private database access, persistent storage/backups and resource/readiness configuration after selecting a platform.
- The review inventories all project-owned files and exercises critical contracts, but neither inventory nor 88% coverage proves the absence of every possible bug. Live browser upload interaction and paid model inference remain unverified here.

**Phase 21 engineering verification is complete; Phase 22 is GitHub Actions CI/CD.** Deployment is a later phase, with platform selection deferred. See [Phase 21](phase21_report.md) for the phase-by-phase matrix, concrete corrections and reproduction commands.
