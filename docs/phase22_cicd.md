# Phase 22: continuous integration and release delivery

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

After committing/pushing the reviewed files, verify the first GitHub-hosted run.
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
Local XML/coverage evidence is in ignored `ci-reports/`; subsequent GitHub runs
will upload their own evidence as workflow artifacts.
GitHub-hosted execution and registry publication have not yet been run.
