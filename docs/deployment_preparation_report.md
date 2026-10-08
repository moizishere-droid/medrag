# Portable deployment preparation — 8 October 2026

> Consolidated 8 October 2026. Dated sections preserve historical findings and test totals; they are not claims about the latest checkout. Current deployment verification is recorded in [deployment preparation](deployment_preparation_report.md).


Scope: prepare and verify portable Docker hosting for the educational MedRAG portfolio demo. No public host, DNS, paid server, release publication or deployment has been created by this work. Existing local user records and database folders were preserved. Verification output is ignored under `ci-reports/`.

## Live Urdu follow-up

One additional authorized `/chat` query was sent using a synthetic account, then that account and its chat were removed. It requested a WHO-based Urdu table of blood-pressure treatment targets and clarification of diagnosis versus treatment. Response time: **13.87 seconds**. Headers and explanations were Urdu; original WHO source excerpts remained English by design. Cited evidence was in scope and the saved answer/citation JSON matched the response. The complete seven-row PDF page 28 source excerpt was attached.

Manual review found duplicated patient rows, awkward Urdu wording and an unsupported diagnosis explanation. Therefore this is a **language/persistence pass, partial answer-quality result**, not a clinical-accuracy pass. Prompt guidance was strengthened to keep patient groups distinct, omit a diagnosis column from a treatment-target table, and state when diagnostic criteria are absent. No further paid query was sent to validate that subsequent wording change. A portfolio demo still needs manual answer review; generated medical text is not certified clinical advice.

## Implemented preparation

- `deploy/compose.portable.yml`, `Caddyfile` and `portable.env.example`: one public HTTPS domain, same-origin browser/API authentication, private data network, only proxy host ports, persistent database/certificate/model volumes, authentication and Secure cookies enabled, no built-in deployment passwords.
- API root path `/api` keeps Swagger/OpenAPI behind the reverse proxy. Forwarded headers assume this private network; do not expose the API port directly.
- Completed `deploy/portable.env` is excluded from Git and Docker build context. Existing local Docker configuration was not replaced; its published database ports now bind to loopback in the source configuration. Existing local containers were not recreated, so this takes effect at their next normal restart/recreation.
- Split API dependencies from notebook/evaluation/test tools. Serving pins update PDF parsing and model libraries; the test image retains the experiment packages.
- Preserve legacy ONNX export on both old local and updated container PyTorch. The existing local virtual environment was not upgraded.
- Add exact-installed-package audits for both serving images to GitHub CI. See [dependency applicability review](deployment_preparation_report.md#dependency-security) for experiment-only findings and model-wheel exclusions.
- Add read-only `deploy/check_readiness.py`: reject disabled authentication, insecure cookies, default/short database passwords, missing API key, incompatible dense/sparse vector schema, missing curated sources or missing expected graph relationships.
- Add safe corpus bootstrap, update, backup and rollback instructions in [deploy/README.md](../deploy/README.md). Database connectivity alone is insufficient readiness evidence.
- Correct the stale upload module description: the API isolates uploads to their owning chat; they do not become account-wide documents.

## Verification recorded so far

- Published main CI: [run 37645175366](https://github.com/moizishere-droid/medrag/actions/runs/37645175366) succeeded for `517eab0357ec2181e615bbe7c50ced197cafc82c`. This does not cover subsequent uncommitted changes.
- Portable Compose parses with synthetic settings; only proxy ports exposed, data network internal, Secure cookie and authentication flags enabled, browser API same origin. Empty secret placeholders are rejected.
- Caddy configuration validation passed; workflow validation passed; five browser authentication bridge tests passed.
- Local readiness/generation/runner checks: 33 passed. Local export compatibility after correction: 2 passed.
- Local corpus gate: PubMed 4,725; OpenFDA 13,167; WHO 4,804; total 22,696; 49,133 expected medical graph relationships. Read-only check, not a new deployment restore.
- Both serving images built; both exact installed Python package audits returned zero known advisory matches. No vulnerability ignore rule is used; publisher model wheels and OS/service packages remain outside this PyPI audit. Packaged frontend sign-in screen passed.
- Upgraded container suite: **340 unit/API/frontend tests and 54 integration tests passed** (394 Python tests). Integration writes were guarded to `medrag_chat_test`; Qdrant tests used throwaway collections; Neo4j checks were read-only.
- Real retrieval/NER startup passed. The new real-model regression matched ONNX scores to PyTorch for a mixed-length batch and a single pair within 1e-4 tolerance.
- Packaged local HTTPS smoke: **15 checks passed**, including Secure/HttpOnly/SameSite cookies, cookie restoration, two-account chat/document-list isolation, logout revocation, trusted/untrusted CORS origins, frontend health and `/api` Swagger routing. TLS was verified against a local test CA, never disabled. Two synthetic accounts were removed afterward. This is an HTTP-client/proxy check, not proof of real-host browser certificate behavior.
- The serving Python advisories scan covers the exact resolved libraries, with no vulnerability ignore rule. Publisher model wheels are excluded from PyPI matching; OS/service-image advisories are outside this scan.

## Remaining public-host gates

Select a Linux host/domain, set actual secrets and spending limits, provision curated-only data, and run the readiness gate. Verify certificate issuance, browser login/refresh, PDF chunk persistence, two-account isolation, source figures/tables and generated answers at the real URL. Test backup restoration in disposable databases. Obtain a green CI run for the final review commit before merging or publishing; earlier main CI does not certify the new changes. No traffic/load, real-host certificate or clinical validation claim is made.

---

<a id="historical-readiness"></a>

## MedRAG portfolio deployment readiness review

> Deployment preparation (8 October 2026): [portable preparation report](deployment_preparation_report.md) tracks current dependency upgrades, hosting configuration and remaining public-host gates. This review below is historical.

> Follow-up (8 October 2026): see [user-perspective testing](phase21_report.md#user-perspective-testing) for the six live answer reviews and subsequently verified code changes. Several reliability findings below have been addressed; dependency review and deployed/hosted verification remain open. The original audit findings are retained as history.

Review date: 7 October 2026. Source snapshot: `7fc1bed8c60e5936c544ef64cce4380e1d0ed777`.

<a id="historical-readiness-decision-and-scope"></a>

### Decision and scope

**Proceed to planning and preparing a portfolio deployment. Do not declare the current snapshot ready for an unrestricted public demo yet.** The core application works under the exercised tests, but this review found a failing current GitHub run and several concrete public-demo gaps. This is an educational resume project demonstrating production practices, not a clinical service or an enterprise production system. Kubernetes, enterprise high availability, and clinical certification are outside this review's recommended scope.

This was a review, not a remediation or deployment run. No source behavior, live account data, or deployment configuration was changed. Credentials were excluded from inventory content; deleted audit files were not restored. New verification evidence is in ignored `ci-reports/`.

<a id="historical-readiness-fresh-verification"></a>

### Fresh verification

| Check | Result and limits |
|---|---|
| Default unit/API/frontend suite | **304 passed**, 50 integration tests deselected, 51.42 seconds |
| Real-service integration suite | **50 passed**, 304 ordinary tests deselected, 94.99 seconds; guarded test PostgreSQL database, throwaway Qdrant collections, read-only Neo4j checks |
| Installed application environment | `pip check` passed; isolated audit tooling did not replace application dependencies |
| Offline repository/artifact inventory | 520 entries inventoried by the existing audit utility; zero artifact-integrity issues reported |
| Notebooks | All 17 notebook files had Python cells parsed and saved error outputs checked; no saved errors. Notebooks were not all re-executed |
| Curated chunk inventory | PubMed 4,725; OpenFDA 13,167; WHO 4,804; total **22,696** unique chunks |
| Data integrity | Serialized schemas, deterministic chunk IDs, embedding/index alignment and finite arrays, image files and links, and saved PDF artifacts checked by the existing audit utility |
| Current GitHub CI | **Failed**, contrary to the earlier successful run documented in Phase 22; details below |
| Runtime dependency advisories | Backend image scan returned **201 advisory entries across 14 installed packages**; applicability requires individual triage |

The inventory includes generated local artifacts. It is not a claim that every file received a line-by-line semantic proof. Manual review focused on runtime source, authentication, ownership, retrieval, upload publication, chat/UI state, database operations, dependencies, container configuration, workflows, and phase reports. Tests passed with deprecation/future warnings, not application test failures. No paid live AI evaluation was run in this review. These checks do not establish clinical correctness, zero security flaws, or a guaranteed response time.

<a id="historical-readiness-review-across-phases-and-folders"></a>

### Review across phases and folders

| Phase / area | Assessment |
|---|---|
| 00–01: setup, configuration, packaging | Package structure and environment compatibility work. Local defaults need hosting-specific overrides |
| 02–04: PubMed, OpenFDA, WHO ingestion | Saved records validate. The configured 36 topics do not imply complete coverage from every source; WHO gaps remain documented |
| 05: chunking | Saved chunk contracts and identifiers validate |
| 06–07: text and image embeddings | Saved arrays/index alignment validate. Image indexing does not establish that the chat interface supports image questions |
| 08–10: Qdrant, sparse and hybrid retrieval | Isolation tests pass. Omitted identity is curated-only; upload visibility is session-scoped |
| 11: reranking | ONNX path and real startup pass. Historical warm benchmarks show improvement, not a hosting latency guarantee |
| 12–13: medical NER and knowledge graph | Extraction/graph contracts and read-only graph checks pass. Medical extraction is not clinically validated |
| 14–15: generation and citations | Covered grounding, language selection and citation functions pass. Model output still requires representative live evaluation |
| 16: PostgreSQL memory | Persistence, ordering, ownership, transactions and concurrency tests pass. Long chat requests hold connections and session locks |
| 17: RAGAS | Retain experiments and documented judge variability; previously suspicious context-recall scores are not a quality guarantee |
| 18–20: application, uploads, API/UI | Covered login persistence, query rendering, titles, source grouping, upload publication and account/session isolation pass. Persistent uploaded-file listing is still missing |
| 21: testing and performance | Current local suite passes all 354 tests. Historical coverage was 89.24%; coverage was not remeasured in this review |
| 22: CI and release delivery | CI workflow and release publication workflow exist. Current main CI fails one timing-dependent test; registry publication and actual hosting deployment remain unverified |
| `backend/`, `frontend/` | Required runtime source/configuration; keep |
| `tests/`, `.github/`, `deploy/` | Required verification and delivery assets; keep |
| `notebooks/`, phase reports in `docs/` | Appropriate portfolio evidence; keep. Historical reports describe their snapshots, not today's readiness |
| `data/` | Useful ingestion/experiment evidence and bootstrap input. Curated database contents must be provisioned separately; they are not automatically restored by starting the API |
| Local environments, caches, database directories, `ci-reports/` | Local operational artifacts, not portfolio source. They are ignored or excluded from deployment context; never erase database directories as routine cleanup |

<a id="historical-readiness-findings-to-resolve-before-a-public-demo"></a>

### Findings to resolve before a public demo

<a id="historical-readiness-1-current-ci-is-red-make-the-login-rate-limit-tests-deterministic"></a>

#### 1. Current CI is red: make the login rate-limit tests deterministic

The [current main run 37612625671](https://github.com/moizishere-droid/medrag/actions/runs/37612625671) for the reviewed commit failed `test_login_attempts_are_rate_limited`: the sixth request returned 401 rather than the expected 429. The ordinary suite passed 304 tests and integration passed 49 of 50. Subsequent container smoke steps were skipped. The earlier [successful run 37601465282](https://github.com/moizishere-droid/medrag/actions/runs/37601465282) belongs to an older commit.

`backend/src/medrag/api/auth.py::rate_limit` uses wall-clock fixed one-minute windows. `tests/integration/test_auth.py` assumes its six attempts occur in the same window. Fresh local tests passed, and a separate guarded-database probe reproduced both cases: six attempts in one window produce five allowed attempts then 429; five attempts before a minute boundary and one after produce six allowed attempts. This confirms the test's boundary sensitivity and provides a plausible explanation of the hosted failure; the hosted log does not record individual attempt timestamps.

Freeze the limiter clock for same-window tests and add an explicit boundary-reset test. Keep the documented fixed-window contract, or deliberately change it if a rolling-minute budget is desired. Obtain a green run for the final commit before publishing.

<a id="historical-readiness-2-review-and-update-vulnerable-dependencies-starting-with-the-upload-parser"></a>

#### 2. Review and update vulnerable dependencies, starting with the upload parser

The scan used exact installed package versions from the cached backend image, whose source/dependency files match this snapshot. Scientific model wheels absent from the advisory index are not certified safe by that scan. Results are in `ci-reports/readiness-dependencies.json`.

| Installed package | Version | Advisory entries |
|---|---|---:|
| biopython | 1.83 | 2 |
| diskcache | 5.6.3 | 2 |
| onnx | 1.17.0 | 16 |
| pdfminer-six | 20231228 | 4 |
| pip | 24.0 | 12 |
| pypdf | 4.2.0 | 85 |
| pytest | 8.2.2 | 2 |
| python-dotenv | 1.0.1 | 2 |
| ragas | 0.3.9 | 2 |
| sentence-transformers | 2.7.0 | 1 |
| setuptools | 65.5.1 | 6 |
| torch | 2.3.1 | 23 |
| transformers | 4.41.2 | 43 |
| wheel | 0.44.0 | 1 |

These are advisory/version matches, not 201 demonstrated exploitable bugs in MedRAG. Some concern unused conversion functions, local model loading, or development tools. Runtime relevance must be assessed individually.

The immediate upload concern is `user_upload.extract_text_from_pdf`, which uses `pdfplumber`, backed by the old `pdfminer.six`. Its upstream [crafted-PDF advisory](https://github.com/pdfminer/pdfminer.six/security/advisories/GHSA-wf5f-4jwr-ppcp) and [CMap-loader advisory](https://github.com/pdfminer/pdfminer.six/security/advisories/GHSA-f83h-ghpp-7wcc) describe unsafe deserialization with additional file-access prerequisites. No exploit was attempted. The maintainer's current first advisory lists patched versions `>=20251230`, which is more recent than that entry's scanner fix metadata. Use current maintainer guidance and a compatible PDF-library update, then rerun extraction/upload tests and image builds. Do not blindly upgrade the whole scientific stack.

Remove evaluation/testing dependencies from the serving image where feasible; retain them in the experiment/test environment. Consider a dependency audit step alongside Dependabot, with reviewed exceptions for nonapplicable findings rather than silently ignoring failures.

<a id="historical-readiness-3-bound-response-time-input-size-and-api-spending"></a>

#### 3. Bound response time, input size and API spending

Both API startup and retrieval construct OpenAI clients without explicit deadlines/retry budgets. The installed SDK defaults include a 600-second read timeout and two retries, while `frontend/streamlit_app.py` waits 60 seconds for chat. Language repair can add another model request. A browser error therefore does not mean backend work stopped.

`ChatRequest.message` rejects blank input but has no length ceiling; a probe accepted 80,000 characters. Session titles also lack a length limit, and generation calls do not set an output-token ceiling. Existing shared request-rate limits and the 20 MB PDF limit help, but do not cap work or cost per request.

Set explicit provider timeouts/retries, bounded query/title/output sizes, and reasonable extracted-page/chunk limits for uploads. Align the UI and proxy timeouts with a documented request budget. Keep chat POSTs unretried automatically; consider idempotency if user retries can overlap an unfinished request. Configure a provider spending budget for a publicly accessible demo.

<a id="historical-readiness-4-correct-healthreadiness-behavior"></a>

#### 4. Correct health/readiness behavior

The `/health` route returns HTTP 200 even when a dependency is down. A fake-dependency probe confirmed `200` with `status=degraded`. The backend Docker health check tests only whether the URL opens, so it accepts that degraded state. It also exposes raw dependency exception text publicly.

Return an appropriate failure status or validate the response body in the container check; expose simple public status and retain details in server logs. Add readiness validation for required Qdrant collection schema and curated data/graph presence. Reachable empty databases currently satisfy dependency connectivity checks but do not establish a usable corpus.

<a id="historical-readiness-5-harden-the-browser-authentication-bridge"></a>

#### 5. Harden the browser authentication bridge

`frontend/auth_bridge/index.html` receives `streamlit:render` messages without checking sender origin/source or validating the payload. It sends messages with a wildcard target origin. This is a static hardening finding, not a reproduced account compromise. Follow [OWASP web messaging guidance](https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html): verify the intended sender, restrict action/API destinations and validate payload shape; use a known parent origin where the component architecture allows. Test refresh/login/logout after changing it.

<a id="historical-readiness-6-configure-a-persistent-private-hosting-layout"></a>

#### 6. Configure a persistent, private hosting layout

`docker-compose.yml` is a development database stack: exposed host database ports and known example passwords must not be copied unchanged onto a public server. Keep database ports private, use hosting secrets, HTTPS, secure cookies (`AUTH_COOKIE_SECURE=true`) and exact allowed browser origins. Preserve authentication enforcement. Configure server-side `MEDRAG_API_URL` separately from browser-facing `MEDRAG_BROWSER_API_URL`, with a domain/cookie layout that supports the frontend's login restoration.

Provision persistent PostgreSQL/Qdrant/Neo4j storage and a repeatable curated-corpus restore/ingestion process. Verify session ownership, refresh/logout, uploaded-content isolation and answers after a restart. Never use ingestion `--reset` casually against a database containing uploads. A simple backup/restore procedure and previous-image rollback are enough for this portfolio scope; enterprise orchestration is unnecessary.

<a id="historical-readiness-useful-improvements-and-honest-demo-limits"></a>

### Useful improvements and honest demo limits

- Add a persistent session upload list. A blank browser file picker after refresh/logout does not delete successfully indexed content; the same account and chat can still retrieve it. There is no current list/delete API or UI for those records.
- Label the interface as an educational portfolio demo, with a short medical-use boundary and guidance against submitting sensitive patient information.
- Curated evidence comes from PubMed, OpenFDA and WHO; uploaded PDFs are an additional session-specific evidence source. Do not advertise that every answer comes exclusively from the three curated sources when uploads are enabled.
- The 36-topic panel describes ingestion scope, not guaranteed complete disease coverage. Scanned PDFs without extractable text are unsupported; OCR is not implemented.
- Prompt-based grounding/language matching is not a mechanical guarantee against hallucinations, prompt injection or missing citation markers. Exercise representative English, multilingual, contextual and insufficient-evidence questions on the deployed demo.
- Keep the documented performance improvements, but measure on the chosen hosting hardware. Historical warm live samples took 4.6–5.8 seconds; startup, long outputs, network delays and concurrency can increase latency. This review did not repeat paid live timing calls.
- The default PostgreSQL pool has ten connections; full chat generation holds a connection and session advisory lock. Run a small concurrent-user test appropriate for a recruiter demo before choosing worker/memory settings.
- Complete README licensing/attribution and describe implemented image indexing separately from chat capabilities. Historical phase reports may retain old outcomes, but the current status should point to the final verified commit.

<a id="historical-readiness-recommended-next-step"></a>

### Recommended next step

Discuss hosting and budget now. Before making the demo public, fix the timing-sensitive CI test, triage the runtime/PDF advisories, bound AI work and costs, correct readiness, and harden the auth bridge. Then perform hosting configuration and persistence/restore checks, run the full suite and hosted CI, publish a tested image and exercise the deployed UI. The existing application need not be rebuilt from scratch, but "everything is perfectly fine" is not supported by the evidence.


---

<a id="dependency-security"></a>

## Serving dependency security review

Reviewed 8 October 2026. The Docker API uses `backend/requirements-runtime.txt`; notebooks, ingestion experiments and tests use `backend/requirements.txt`. The API does not install RAGAS, LangChain, OpenCLIP, pypdf, pytest or Streamlit. The frontend has its own requirements.

The serving pins update the PDF parser pair, PyTorch, Transformers, Sentence Transformers, ONNX and python-dotenv. Experiment-only pypdf, Biopython and pytest are also updated. The CPU PyTorch wheel is used in Docker; no CUDA libraries are required. The legacy ONNX exporter is selected explicitly and must pass real-model startup checks. These changes are not approved by version numbers alone: verify clean resolution, extraction, NER, reranking, tests and image startup.

The previous exact-image audit returned 201 advisory entries across 14 packages. Duplicate advisory IDs appear in the advisory service and are not 201 independently demonstrated exploits. The CI audit now uses exact installed serving-package versions and fails on unreviewed advisory matches.

<a id="dependency-security-serving-audit-result-and-experiment-only-findings"></a>

### Serving audit result and experiment-only findings

Both exact-installed serving-image audits returned zero known Python advisory matches. No vulnerability ignore rule is used in CI. `diskcache` is absent from both serving images after removing evaluation dependencies; its local-pickle advisory therefore needs no serving exception. RAGAS is also absent. The offline experiment environment can still include these packages and must use trusted evaluation inputs and trusted cache directories. It is not the public API environment.

The three pinned spaCy/scispaCy model wheels come from their documented publisher URLs and are not PyPI packages; the PyPI advisory audit excludes those model distribution names. Their publisher, artifact integrity and model startup remain separate checks. The audit covers Python packages, not every OS package or service container.

RAGAS remains in the offline experiment/test environment. Its reported multimodal context URL/file handling SSRF issue is not exposed by the chat API because RAGAS is excluded from the serving image. Use only trusted evaluation inputs; do not turn its evaluator into a public endpoint.

Primary PDF maintainer guidance: [crafted-PDF advisory](https://github.com/pdfminer/pdfminer.six/security/advisories/GHSA-wf5f-4jwr-ppcp), [CMap-loader advisory](https://github.com/pdfminer/pdfminer.six/security/advisories/GHSA-f83h-ghpp-7wcc). The pinned pdfplumber release uses pdfminer.six 20260107, beyond the maintainer's 20251230 fix boundary.
