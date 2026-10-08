# Phase 21: Testing and final engineering review

> Consolidated 8 October 2026. Dated sections preserve historical findings and test totals; they are not claims about the latest checkout. Current deployment verification is recorded in [deployment preparation](deployment_preparation_report.md).


Follow-up: see [chat UI, persistent login and topic titles](phase21_report.md#ui-follow-up)
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

Final totals and coverage are recorded in [the current audit validation](phase21_report.md#project-audit-validation),
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

---

<a id="ui-follow-up"></a>

## Phase 21: chat UI and login follow-up

Date: 2026-10-06. Supplements the original Phase 21 audit and its artifacts.

<a id="ui-follow-up-changes"></a>

### Changes

- Login/register sets an HttpOnly, SameSite=Lax cookie with the token's lifetime
  (24 hours by default). Streamlit restores the token from its connection cookie
  after refresh. Sign-out removes the cookie and revokes its database token.
  Expired/invalid cookies cannot restore access; rejected cookies are ignored for
  the current Streamlit connection to prevent an endless rerun loop. Explicit
  bearer headers take precedence. Cookie-authenticated writes reject untrusted
  browser origins. No token is stored in localStorage or a URL.
- The browser component performs login/register/logout against the API so the
  browser receives the cookie; the component then reconnects Streamlit. API and
  UI must use the same hostname. Local ports 8501/8502 are allowed by default;
  configure `CORS_ORIGINS` for other ports. `MEDRAG_API_URL` and
  `MEDRAG_BROWSER_API_URL` separate server and browser addresses. HTTPS hosting
  requires `AUTH_COOKIE_SECURE=true` and a shared hostname/reverse proxy.
- Untitled sessions display `New Chat`. The first successful question names the
  session in the same locked transaction as messages/citations. "What is type 2
  diabetes?" becomes "Diabetes Type 2". Titles use deterministic normalization
  (8 words/80 characters), avoiding another paid model request. Later turns and
  explicit titles are preserved. Failed turns roll back the title too.
- The question is rendered before the blocking answer request; Thinking appears
  in the assistant message. Citation source entries group chunks by document
  ID/URL and keep all original answer markers. Different document IDs with the
  same filename remain separate. Historical citations without IDs fall back to
  title. Public health/config checks are cached for 30 seconds per connection;
  private sessions/history/evidence are not cached.
- Local BM25 and cross-encoder models warm at startup, with guarded single
  cross-encoder construction. Per-stage timings identify retrieval/generation
  delays without logging user questions. No answer/evidence cache crosses users.

<a id="ui-follow-up-verification"></a>

### Verification

- Full default suite: 298 passed (`audit/ui_followup_unit.xml`); full real-service
  integration suite: 49 passed (`audit/ui_followup_integration.xml`). The affected auth/lifespan checks also passed
  after the final origin/warmup changes (14 passed). PostgreSQL tests use
  `medrag_chat_test`, Qdrant uses disposable
  collections, and Neo4j is queried read-only.
- Browser verification used isolated ports 8003/8503 and an isolated test account
  in the test database. Login succeeded; refresh remained signed in. During a
  four-second simulated answer, the question and Thinking were both visible.
  The answer updated the session selector to Diabetes Type 2 and showed one
  source entry for markers [1], [2]. Sign-out returned to the login form.
  Generation/evidence in this browser fixture were simulated; this is not a
  live medical-answer quality or PDF-upload test.
- The screenshot `audit/phase21_chat_ui.png` shows the simulated final UI. Its
  fixture deliberately uses the generic Uploaded document title.
- The project artifact inventory was rerun: 501 tracked-workspace files checked,
  no consistency issues and no saved notebook error outputs.
- A neutral real-model request measured warm retrieval at 15.137 seconds and
  generation at 2.930 seconds. Local short-input reranking measured cold 3.195
  seconds versus warm 0.135 seconds. A separate 20-full-chunk CPU benchmark took
  10.902 seconds at the default four threads; reducing to one thread worsened it
  to 17.455 seconds with unchanged top-five ranking. Thread settings were not
  changed. Warmup removes first-request loading, but sustained CPU/cloud latency
  remains a performance limit; faster hosting/inference should be benchmarked
  before promising a response-time target. One live embedding/answer call was
  performed in this follow-up; the earlier audit's unrun-work list is historical.

<a id="ui-follow-up-additional-rerun-language-and-topic-panel-fixes"></a>

### Additional rerun, language and topic-panel fixes

- The installed Streamlit selectbox serializes displayed labels, even when its
  Python options are stable IDs. Duplicate `New Chat` labels were reproduced in
  the browser switching to another empty session on submission. Duplicate names
  now get simple numbered suffixes. A callback saves each submitted question
  and its session before sidebar/history reruns; pending questions pin selection
  to that session and are processed once. The first question also provides a
  provisional topic label while the successful backend transaction persists it.
- Intermittent real API disconnects were reproduced through `localhost` while
  direct `127.0.0.1` requests succeeded. Server requests now default to IPv4;
  browser auth stays on `localhost` for cookie sharing. Safe GET requests retry
  interrupted connections three times. Chat, upload and creation writes are
  never automatically replayed. On a failed session read, the UI retains the
  same account's last known list, offers Retry loading chats, and does not claim
  that there are no sessions. Logout/expiry clears this cache. A fresh connection
  without cached sessions must reconnect to load them; it does not delete them.
- Both direct generation and chat memory detect language from the original
  current query with a seeded local langdetect factory and rules for short
  English/Spanish questions and Roman Urdu. History, retrieval rewrites and
  sources do not select response language. Ambiguous standalone medical terms
  default to English. A clear script/statistical mismatch triggers one bounded
  regeneration; a persistent mismatch raises a 502 and does not commit the turn.
  This is a practical guard, not perfect language identification for every mixed
  or ambiguous input. Normal successful requests make no extra model call.
- The sidebar lists all 36 configured topics from `medrag.topics.TOPICS`, also
  imported by ingestion. It names PubMed, OpenFDA drug labels and WHO guidelines,
  explains coverage differences and acknowledges session-scoped uploaded PDFs.
  It does not claim every condition has evidence from all three sources.
- Browser verification with two unnamed chats reproduced the disappearing
  question, then confirmed the fix, a Diabetes Type 2 label and saved history
  after refresh (`audit/phase21_chat_refresh.png`). The topic panel was opened and
  verified with all 36 names (`audit/phase21_topics_panel.png`). Tests cover forced
  sidebar reruns, distinct duplicate labels and interrupted session reads.
- Live model checks against a small supplied test context returned English for
  the exact English follow-up, Spanish for a Spanish question and Urdu for an
  Urdu question, despite a previous Russian response. English/Spanish retained
  the citation marker; Urdu omitted it in that sample. General citation adherence
  remains a model-quality limit; this change validates language, not every claim.
  See [langdetect](https://pypi.org/project/langdetect/) for the detector's documented
  ambiguity and reproducibility settings. The dependency is pinned at 1.0.9.

<a id="ui-follow-up-isolation-remains-enforced"></a>

### Isolation remains enforced

Missing retrieval identity means curated-only. An explicit session scope adds
only that session's published uploads. Full corpus access requires the internal
keyword `full_corpus_evaluation=True`; it cannot be combined with an identity
and is not exposed by `/chat`. See `retrieval_isolation.md` for affected internal
evaluation scripts and notebook call sites. These UI changes do not widen scope.

Restart the backend and Streamlit processes to load these changes. Sign in once
after upgrading to establish the new browser cookie. CI/CD and hosting remain
the next phases; this follow-up does not implement or deploy them.


---

<a id="project-audit"></a>

## MedRAG phase-by-phase audit
Updated 6 October 2026 during [Phase 21](phase21_report.md). This audit covers project-owned source, scripts, configuration, tests, phase reports 00–21, all 17 notebooks, and saved data artifacts. The per-file inventory is in [audit/inventory.json](audit/inventory.json). Credentials, Git internals, installed third-party packages, caches, generated audit outputs, and live database storage directories are excluded. Database behavior is checked through isolated integration tests instead. File inventory/syntax checks and semantic review are distinct; full notebook execution and clinical validation are not claimed.

<a id="project-audit-findings-and-corrections-by-phase"></a>

### Findings and corrections by phase

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

<a id="project-audit-validation"></a>

### Validation

The final complete run passed **317 tests**: 272 default unit/API/frontend tests and 45 integration tests against the running local PostgreSQL, Qdrant and Neo4j services. There were no failures, skips or expected failures. Package statement coverage is **88%**, up from 60% at the start of this review. The actual API lifespan, health checks and authenticated session creation also passed against real services with PostgreSQL writes isolated to the test database. See [JUnit results](audit/phase21-tests.xml), [coverage JSON](audit/coverage.json) and the [Phase 21 report](phase21_report.md).

The artifact inventory validates all saved records, notebook code syntax, PDF pages, PNG integrity, vector dimensions/finiteness/index alignment, deterministic point IDs, image links and curated embedding token limits. It reports no artifact-integrity defects. There are 22,696 unique curated text chunks: 4,725 PubMed, 13,167 OpenFDA and 4,804 WHO. All 17 notebooks have no saved error outputs. `pip check` reports no broken installed requirements, and the pinned Compose configuration validates.

PostgreSQL writes use the guarded `medrag_chat_test` database. Qdrant tests use uniquely named temporary collections. Neo4j integration checks are read-only. The Streamlit AppTest and offline imports require no external services; OpenAI/model encoders are mocked except the installed NER smoke test. Production data was not deleted, refreshed, reembedded or rescored. Full notebooks, paid model requests and fresh source downloads were not run. Test coverage measures the `medrag` package, not the frontend or runner statements.

<a id="project-audit-previously-reported-blockers-now-resolved"></a>

### Previously reported blockers now resolved

- Authentication, account-owned session lists, revocable/expiring tokens and shared rate limits are implemented and tested. Disabling auth permits private routes only for local development clients.
- Database-backed session locks serialize concurrent operations on one chat. Different sessions continue concurrently.
- Chat messages and citations commit atomically; a citation failure rolls back the complete turn.
- Uploads remain hidden while staged. A failed embedding/index operation cleans up; deterministic document IDs and a SQL registry support retries. A failed publication after commit is repaired without reembedding.
- Missing retrieval IDs cannot expose uploads. Full-corpus evaluation is an explicit internal opt-in and still hides staged points.
- Database image tags are replaced with immutable digests from the actual tested local images. Fresh Linux provisioning is still a CI task.

<a id="project-audit-remaining-limits-and-next-phase"></a>

### Remaining limits and next phase

- Clinical truth of automatically extracted graph relationships is not established. Negation, ambiguous entities and source-coverage gaps remain; graph candidates cannot override cited source text.
- General uploads have no OCR path; scanned PDFs without text are rejected. Uploaded PDFs do not use WHO-specific table/layout processing.
- Chat generation uses text contexts. Image embeddings and heuristic figure links do not provide full multimodal chat.
- RAGAS scores are historical; paid rescoring and LLM-as-judge variability remain outside these engineering checks.
- The final checkout has not been installed from scratch on a clean Linux runner. This is a Phase 22 gate. Current Neo4j read-only tests require a populated graph; fresh CI needs a dedicated deterministic seed.
- Account uploads remain scoped to their chat session. Historical unowned sessions are not claimed by newly registered accounts.
- The local Compose defaults are development settings. Deployment requires TLS, platform secrets, private database access, persistent storage/backups and resource/readiness configuration after selecting a platform.
- The review inventories all project-owned files and exercises critical contracts, but neither inventory nor 88% coverage proves the absence of every possible bug. Live browser upload interaction and paid model inference remain unverified here.

**Phase 21 engineering verification is complete; Phase 22 is GitHub Actions CI/CD.** Deployment is a later phase, with platform selection deferred. See [Phase 21](phase21_report.md) for the phase-by-phase matrix, concrete corrections and reproduction commands.


---

<a id="user-perspective-testing"></a>

## User-perspective testing and reliability follow-up

Date: 8 October 2026 (Asia/Karachi).

<a id="user-perspective-testing-outcome-and-scope"></a>

### Outcome and scope

Exactly **six live `/chat` requests** were made, respecting the requested query limit. This was a portfolio-demo assessment, not clinical certification or an exhaustive production/load/security audit. The running FastAPI service used real Qdrant, Neo4j, PostgreSQL and OpenAI dependencies. Two synthetic accounts and a one-page synthetic PDF were created and removed afterward; existing user accounts, sessions, uploaded files and curated vectors were not altered. The six live responses were reviewed against their actual, scoped citation payloads, not judged solely by HTTP success.

The initial request-readiness probe timed out during development auto-reload before any chat request; it incurred no model query. A subsequent readiness wait allowed all six cases to complete. The saved raw results are in the ignored local file `ci-reports/user-perspective-live.json`, not required to run the application.

<a id="user-perspective-testing-six-live-answer-reviews-before-the-new-fixes"></a>

### Six live answer reviews before the new fixes

| Scenario | Observed response time | Review |
|---|---:|---|
| english_definition | 12.72 s | Passed evidence review; two WHO chunks support the main explanation. |
| english_followup | 7.80 s | Passed meaning/language review; cites redundant FDA template chunks. |
| urdu_language_switch | 8.38 s | Failed semantic review: confused blood pressure with eye pressure; unrelated glaucoma and damaged PDF evidence were cited. |
| verified_figure | 7.37 s | Image delivery passed. Answer review failed: flattened columns were misinterpreted and some claimed criteria were absent from the cited chunk. |
| evidence_table | 8.48 s | Partial: Markdown table displayed, but damaged PDF text was used to infer diagnosis and treatment thresholds were mixed into a diagnosis question. |
| private_upload_and_insufficient_evidence | 6.46 s | Study code correct; no unsupported cure accepted; malicious uploaded instruction not obeyed. Minor attribution wording was overstated. |

Observed range: **6.46–12.72 seconds**; median **8.09 seconds**. These are six local observations under development conditions, including startup and concurrent automated testing. They are not a throughput benchmark, post-fix latency measurement, or hosting performance guarantee.

All six replies used the detected query language and had resolvable citation markers whose source chunks were within the session's permitted scope. All six answers and their citation JSON matched persisted history reads. These structural checks did **not** establish medical/semantic correctness: the Urdu and figure cases demonstrate that distinction.

<a id="user-perspective-testing-user-flows-verified-without-further-model-queries"></a>

### User flows verified without further model queries

- Anonymous sessions rejected; a second account cannot list or read the first account's chats.
- Cookie-based API authentication survives a new client connection representing refresh. Sign-out revokes the old cookie/token; signing back in restores access to the account's chats.
- Duplicate PDF upload returns the same document ID; malformed PDF returns 422.
- The private synthetic upload is retrievable only within its owning chat. Another chat, and omitted retrieval identity, cannot see its Qdrant point.
- Uploaded evidence remains indexed after sign-out; the final live query correctly returned `PORTFOLIO-4827` from the synthetic PDF after signing back in.
- Correct verified dengue PNG returned by the authenticated media endpoint; old tyre asset excluded.
- Source grouping, immediate question rendering, thinking state, chat switching, read retry/recovery, wrapped table display and media-unavailable handling are exercised by Streamlit AppTest.
- This run did not use a real browser to repeat every widget/cookie flow; API-cookie and AppTest checks are the evidence for those flows.

<a id="user-perspective-testing-changes-made-after-reviewing-the-six-live-answers"></a>

### Changes made after reviewing the six live answers

1. **Multilingual retrieval:** non-English standalone questions now receive an English retrieval rewrite even when the chat has no history. Final generation still receives the original question and its current language. Rewrite instructions preserve medical meaning and ignore unrelated older topics. A deterministic test checks the actual memory pipeline with an Urdu question.
2. **Reproduced mistranslation guard:** a blood-pressure query that did not request an eye topic cannot publish the reproduced eye-pressure explanation. The existing maximum two-attempt generation policy repairs a mismatch or rejects the answer. This narrow guard is not a general medical-factuality validator.
3. **Evidence quality:** unresolved `(cid:N)` PDF text is excluded before reranking, and direct generation context also masks damaged blocks. Intact candidates can fill the final evidence slots. Extraction damage remains in underlying saved/indexed artifacts; no corpus rebuild was performed.
4. **Source figures:** figure-heading chunks are reduced to their verified caption/page metadata in generation context; flattened diagram cells are not available to the text model as clinical evidence. Full original source pages still display below cited replies. The model must not infer diagnostic details, category relationships or disease progression from captions or unseen pixels.
5. **Grounding instructions:** source documents and history are untrusted data, previous answers are not evidence, source-injected commands are ignored, and diagnosis criteria must be distinguished from treatment thresholds/control targets. Tables should use supported rows and explicit missing-evidence statements.
6. **Source links and titles:** WHO filename slugs such as `dengue_fever` resolve canonical source IDs such as `dengue fever`; the original-PDF link is restored. Chat titles use the first question rather than appended instructions such as "explain simply and cite sources".
7. **Private durable upload inventory:** `GET /sessions/{session_id}/documents` verifies session ownership and returns filename/document ID/chunk count only. The frontend reads this registry, making already-indexed PDFs visible after refresh/sign-in. Read requests use the read rate budget; only upload POSTs use the upload-write budget.
8. **Bounded interactive work:** questions ≤4,000 characters, supplied titles ≤80 characters, rewrites ≤256 output tokens with a 10-second timeout, answers ≤1,000 output tokens, provider clients with zero SDK retries and 20-second answer/10-second embedding timeouts. At most one existing language/topic repair remains possible. Empty or token-truncated completions are rejected. UI chat waiting is 90 seconds. These bound provider operations, not total CPU/database elapsed time.
9. **Bounded uploads:** existing 20 MB limit plus 100-page and 200,000 extracted-character limits for private PDFs. There is no OCR or isolated-process parser deadline in this implementation.
10. **Failure behavior:** provider errors return safe 503/504 messages; raw upstream details are not sent to users. Dependency health failure returns 503 with sanitized status, making Docker health checks fail correctly. The UI continues to distinguish degraded service from an unreachable API. Health checks still verify connectivity, not complete corpus/schema/model readiness.
11. **Browser authentication messages:** accept only the expected parent source/origin; validate nonce, action, credential shape and API URL; use an exact parent origin for replies. Remote APIs require HTTPS; HTTP remains available only for loopback development. Five Node tests cover trusted login, spoofing, unsafe actions/URLs, local logout and malformed messages; CI now runs them.
12. **Reliable CI rate-limit test:** freeze time in the failed-login limiter test so five attempts and the sixth denial cannot cross a minute boundary. Runtime fixed-window policy is unchanged.
13. **Portfolio boundary:** the main UI labels this as an educational demo and asks users to avoid personal patient data.

<a id="user-perspective-testing-verification-status"></a>

### Verification status

Baseline: **323 default tests + 51 real-service integration tests passed**. After the final changes, **336 default tests + 53 real-service integration tests + 5 browser-authentication JavaScript tests passed**. Both Docker images built successfully. The packaged backend passed verified-figure, diagram-context and WHO-link checks with network disabled and dummy credentials; the packaged frontend rendered the sign-in screen with an offline mock API. The pinned workflow checker, source compilation and diff checks passed. The running backend reported all three dependencies healthy. A packaged UI check also prompted a correction: cookie restoration now accepts only a real nonempty string of bounded length, with a regression test for the sign-in screen. Hosted CI and real hosted deployment were not run.

No additional paid answer queries were made after the fixes. Regression tests demonstrate the corrected code paths and guard behavior; post-fix live semantic validation of the previously failing Urdu and diagram cases remains outstanding under the six-query budget. Do not report six perfect answers or clinical accuracy from this exercise.

<a id="user-perspective-testing-remaining-public-deployment-gates"></a>

### Remaining public-deployment gates

- Recheck the previously failing Urdu/diagram answers when another small live-query budget is available; consider a stronger available model only after measuring its cost and answer quality.
- Repair original PDF extraction and retain structured/caption/page provenance before relying on diagrams or merged tables for clinical details. The current guard excludes uncertain content rather than fabricating repairs.
- Review and update vulnerable runtime dependencies, especially the PDF parser, using the earlier dependency review. This task did not refresh dependency versions or certify their security.
- Run hosted CI on the final commit; this working-tree run does not prove a GitHub Actions success or a published release.
- Verify HTTPS, secure cookies, private database networking, persistent volumes, secrets, spending limits, backups/restore and startup behavior on the selected host.
- Perform a small deployed concurrent-user/latency check. Connection/session-lock tests here are not a traffic load test.

The project now has stronger portfolio-demo safeguards and user-facing verification. Calling it a fully verified production medical system would exceed the evidence.

<a id="user-perspective-testing-review-references"></a>

### Review references

The [WHO hypertension fact sheet](https://www.who.int/en/news-room/fact-sheets/detail/hypertension) and [WHO dengue outbreak toolbox](https://www.who.int/emergencies/outbreak-toolkit/disease-outbreak-toolboxes/dengue-outbreak-toolbox) were used to check the distinction between source-supported concepts and the problematic generated summaries. They were not added to retrieval or supplied as new live evidence.

Request parameters and prompting were checked against the installed SDK and official [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) and [GPT-4.1 prompting guide](https://developers.openai.com/cookbook/examples/gpt4-1_prompting_guide). The configured model remains `gpt-4.1-nano`; no model migration was made.

<a id="user-perspective-testing-urdu-source-excerpt-follow-up"></a>

#### Urdu source excerpt follow-up

The saved hypertension extraction for PDF page 28 contains all seven rows, including the final conditional recommendation and evidence rating. The screenshot shows only the upper portion. These are original English source cells, not a translated answer table. Single-column boxes now display as text without an invented Column 1 header, with source-language and excerpt labels; every extracted row is retained. Generated answer table headers and explanations are explicitly instructed to follow the query language while preserving values and units. Relevant frontend, generation and source-visual tests: 43 passed. No additional live model queries were sent; the new instruction has not been validated with another live Urdu response.
