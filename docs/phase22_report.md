# Phase 22 Report: GitHub Actions CI and release delivery

Date: 7 October 2026 (Asia/Karachi).

## Outcome

Continuous integration is implemented and verified both locally and on GitHub.
Pull requests and main-branch pushes automatically check the project, run tests,
build application containers, and verify packaged startup. A separate release
workflow prepares delivery through GitHub Container Registry after checks pass.
Registry publishing has not been verified, and no hosting deployment is configured.

This phase turns the Phase 21 tests into repeatable checks on a clean Linux
environment. It does not change the retrieval privacy contract, automatically
ingest medical data, or deploy the application to a public platform.

## Files delivered

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Automated tests, coverage, builds, startup checks and reports |
| `.github/workflows/release.yml` | Rerun CI before publishing backend/frontend release images |
| `.github/dependabot.yml` | Propose updates to Actions, Docker and Python dependencies |
| `deploy/Dockerfile` | Test, backend and lean frontend image targets |
| `deploy/compose.ci.yml` | Isolated PostgreSQL, Qdrant, Neo4j and packaged test services |
| `deploy/prepare_ci_services.py` | Wait for services and seed a guarded synthetic graph |
| `deploy/smoke_runtime.py` | Check actual packaged server health and authentication |
| `frontend/requirements.txt` | Separate frontend dependencies |
| `.dockerignore` | Allowlisted build context excluding credentials and local artifacts |
| `tests/unit/test_ci_service_guard.py` | Reject non-CI targets before any network/database access |
| `.gitignore` and `README.md` | Ignore generated CI evidence and document the workflow |

GitHub Actions checks pull requests, pushes to `main`, and manual CI runs.
The release workflow reruns the same checks before publishing backend and
frontend images to GitHub Container Registry. Actual staging/production
deployment remains pending the hosting-platform decision.

## Workflow behavior

`ci.yml` builds a clean Python 3.11 Linux test image, checks source syntax,
runs the default unit/API/frontend suite with coverage, starts three disposable
database services, seeds a synthetic graph fixture, and runs all non-live
integration tests.
Coverage accumulates across both suites before enforcing an 85% package
statement-coverage floor, below the previous combined approximately 88% baseline.
Retrieval warmup remains enabled to exercise the real CPU ONNX startup path.
It then builds both application images, starts the actual
packaged servers and checks backend health, required authentication, rejection
of unauthenticated session reads, and Streamlit server health. This is a
server-startup check; Streamlit AppTest also renders the packaged sign-in page.
It does not exercise browser cookies or a live chat response.

JUnit XML and coverage XML are retained as workflow artifacts for 14 days.
Failure logs are captured and disposable services are removed even on failure.
No paid OpenAI calls or production secrets are needed; test code supplies fakes
for external AI calls. Model/tokenizer downloads still require network access.

`release.yml` runs on a `v*` tag or manual dispatch. Publishing is permitted
only for a version tag or `main`; checks must pass first. Images are named:

```
ghcr.io/moizishere-droid/medrag-backend:sha-<full-commit>
ghcr.io/moizishere-droid/medrag-frontend:sha-<full-commit>
```

The full commit tag identifies the source used for the image. Treat these tags
as write-once release references; the registry does not enforce immutability.
Use the image digest when deploying for an immutable reference. The workflow
uses GitHub's job token with package-write permission only in the publish job.
No registry password needs to be added manually. Failed publication of one
image must be resolved before deploying the pair.

## Isolation and dependencies

`deploy/compose.ci.yml` uses its own network with no host-port bindings and no
production volume mounts. CI never loads the repository's `.env`. Its test
password is a disposable fixture, not a deployment credential. PostgreSQL tests
use the guarded `medrag_chat_test` database; vector tests use temporary
collections. The graph helper accepts only the three exact CI service names
and seeds explicitly synthetic nodes. This verifies graph contracts, not the
quality or completeness of the ingested medical corpus.

The Docker build context uses an allowlist. Credentials, local databases,
uploads, notebooks, audit artifacts and model caches are excluded. Public WHO
JSON is included for citation URL lookup. Images run as an unprivileged user;
backend model/export cache directories remain writable. CPU PyTorch is used
instead of CUDA. The frontend installs its smaller dependency list separately.
The backend currently includes the full project dependency set, including
ingestion/evaluation tools; a lean runtime split is a later optimization.

Actions and container bases are pinned to commits/digests.
Docker dependency layers use GitHub's build cache to avoid repeated downloads.
Cache misses still build the environment from the declared requirements.
Disposable model volumes share downloaded weights and exports between checks
and packaged startup within a run; cleanup removes them.
Dependabot proposes
weekly updates for Actions, Docker and Python requirements. Review coupled
FastAPI/Starlette/Uvicorn and RAGAS/LangChain changes together. Dependency
compatibility checks and update proposals do not constitute a vulnerability
audit or a security certification.

## Local reproduction

Run from the repository root with Docker available. These examples use Bash
(the same shell as the GitHub runner):

```bash
export COMPOSE_PROJECT_NAME=medrag-ci-local
export MEDRAG_CI_REPORTS="$PWD/ci-reports"
mkdir -p "$MEDRAG_CI_REPORTS"
chmod 777 "$MEDRAG_CI_REPORTS"
docker build --target test -f deploy/Dockerfile -t medrag-test:ci .
docker compose -f deploy/compose.ci.yml run --rm -T tests python -m pytest -q \
  -m 'not integration and not live' --junitxml=/reports/unit.xml
docker compose -f deploy/compose.ci.yml up -d vector-ci graph-ci postgres-ci
docker compose -f deploy/compose.ci.yml run --rm -T tests python deploy/prepare_ci_services.py
docker compose -f deploy/compose.ci.yml run --rm -T tests python -m pytest -q \
  -m 'integration and not live' --junitxml=/reports/integration.xml
docker build --target backend -f deploy/Dockerfile -t medrag-backend:ci .
docker build --target frontend -f deploy/Dockerfile -t medrag-frontend:ci .
docker compose -f deploy/compose.ci.yml up -d api-ci ui-ci
docker compose -f deploy/compose.ci.yml run --rm -T tests python deploy/smoke_runtime.py
docker compose -f deploy/compose.ci.yml down -v --remove-orphans
```

In PowerShell set `$env:COMPOSE_PROJECT_NAME` and `$env:MEDRAG_CI_REPORTS`
instead of `export`; use single-line commands rather than Bash continuations.

## GitHub activation and deployment follow-up

The initial implementation was committed and pushed; the first main-branch
GitHub-hosted run passed, as recorded below.
Make **Tests and container checks** a required main-branch check using repository
rules. Protect release tags and restrict who can publish releases. Enable Actions
and package publishing if repository/organization policies require it. None of
these repository settings are changed by adding workflow files.

Choose hosting before adding its deployment job. Configure isolated staging and
production environments, secrets, HTTPS, browser API URLs and credentialed CORS.
Keep authentication enabled and use secure cookies behind HTTPS. Store database
data persistently, back it up, provision the curated corpus/graph, and keep
ingestion separate from application startup. Supply runtime credentials through
the host, not image build arguments. On AWS prefer OIDC for deployment access.
After health/user-flow checks, approve production and retain the previous image
digests for rollback. Database changes may need a separate rollback plan.

Known UI follow-up: a refresh/logout clears the file picker, while successfully
indexed uploads remain available in their original account-owned session.
A persistent uploaded-document list is not yet implemented.

## Verification record

Verified locally on 7 October 2026 using clean Linux Docker images:

| Check | Result |
|---|---|
| GitHub workflow syntax, expressions and shell scripts (`actionlint` 1.7.12) | Passed |
| Compose configuration and packaged Python syntax | Passed |
| Fresh backend/frontend dependency installation and `pip check` | Passed |
| Unit/API/frontend suite | 304 passed; no skips or failures |
| Disposable-service integration suite, including real ONNX startup | 50 passed; no skips or failures |
| Combined package statement coverage | 89.24%; 85% gate passed |
| Packaged backend/frontend health and authentication enforcement | Passed |
| Packaged frontend sign-in rendering and unavailable-backend recovery | Passed |

The full local CI reproduction made no paid AI calls. The first backend build
downloaded the complete scientific dependency/model set; cached rebuilds reused
those layers. One local Docker snapshot/export error cleared on a cached retry;
no application or user database reset was needed. The 304-test Windows default
suite also passed; an initially misplaced unit-only coverage gate was corrected
to apply to combined unit/integration coverage, then verified in Linux.

Disposable local CI containers, networks and volumes were removed after checks.
Local XML/coverage evidence is in ignored `ci-reports/`; GitHub runs upload
their own evidence as workflow artifacts.

## GitHub verification

The **MedRAG CI** run for commit
`dc28b8728ce26c8f7b5f6e1aec1c908e5974a862` completed successfully:

- [Run 37601465282](https://github.com/moizishere-droid/medrag/actions/runs/37601465282).
- Workflow start: 7 October 2026, 2:33:46 PM Pakistan time.
- Final workflow update: 2:44:12 PM Pakistan time; approximately 10 minutes 26 seconds.
- **Tests and container checks** job: successful.
- Workflow validation, clean dependency build, unit/API/frontend tests,
  integration tests, both application builds, packaged health/authentication
  checks, sign-in rendering, artifact upload and cleanup all succeeded.

The 354-test count and 89.24% coverage above are the measured local Linux
results. GitHub job/step conclusions independently confirm successful hosted
execution; the hosted artifacts retain its detailed test and coverage results.
Separate Dependabot pull requests may fail their checks and require review;
those failures do not change the successful main-commit result.

## Remaining work and phase boundary

1. Confirm repository rules require **Tests and container checks** before merging.
   Branch/ruleset settings were recommended but are not verified by this report.
2. Review dependency-update pull requests individually, preserving compatible pins.
3. Trigger and verify a release publication when ready; no registry publication
   was performed as part of these checks.
4. Choose hosting, then configure staging, persistent databases, secrets, HTTPS,
   deployment checks, production approval and rollback.
5. Address the persistent uploaded-document list separately; clearing the browser
   file picker does not delete successfully indexed session-scoped content.

**Phase status:** CI is verified. Release delivery is implemented but unverified
in the registry. Staging/production deployment is pending the platform decision.
