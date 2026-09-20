# Phase 18: FastAPI — Report

## Phase Objective

Expose the full MedRAG pipeline — hybrid retrieval, reranking, grounded generation, citations, knowledge graph enrichment, and session-based chat memory — as a real HTTP API, providing the foundation both the Phase 19 upload pipeline and the Phase 20 Streamlit frontend will build on.

## What Was Built

- **`backend/src/medrag/api/main.py`** — the FastAPI app: `lifespan`-managed backend connections (Qdrant, Neo4j, Postgres, OpenAI, plus the WHO source URL lookup), CORS middleware, and four endpoints.
- **`backend/src/medrag/api/models.py`** — explicit Pydantic request/response models for every endpoint.
- **`POST /sessions`**, **`GET /sessions/{session_id}`** (with proper 404 handling), **`POST /chat`** (the main endpoint), **`GET /health`** (per-dependency status).
- Two integration fixes to existing Phase 15/16 code, made necessary by wiring them together for the first time through a real API (see Key Design Decisions and Challenges below).

## Key Design Decisions

1. **The notebook-first methodology was deliberately adapted, not abandoned, for this phase.** A running HTTP server has no natural fit with notebook cells. Rather than force the tool, validation was done via FastAPI's `TestClient` for in-process, per-endpoint testing — preserving the same "build one piece, verify it, then the next" rhythm as every prior phase — with a real `uvicorn` + `curl` check reserved for the final validation step, to confirm genuine server behavior that `TestClient`'s in-process shortcuts can't fully guarantee.
2. **Backend clients are created once at startup via `lifespan`, stored on `app.state`, never recreated per-request.** A fresh Neo4j driver or Qdrant client on every single API call would be wasteful and slow; `lifespan` is the standard FastAPI mechanism for this exact pattern.
3. **`/health` checks each dependency individually rather than returning a bare boolean.** Distinguishing "the app process is running" from "the app can actually serve a real request" matters for Phase 22/23 deployment, where a degraded dependency should be visible and diagnosable, not hidden behind a blanket `200 OK`.
4. **CORS middleware was added now, even though nothing currently calls this API cross-origin.** Phase 20's Streamlit frontend will run on a different port than this API, and failing to anticipate that now would surface as a confusing new bug in Phase 20 rather than a already-understood, already-solved problem.
5. **Authentication and rate limiting are explicitly out of scope**, stated as a deliberate boundary rather than left as a silent gap — reasonable for a portfolio project without public production traffic.
6. **`GET /sessions/{session_id}` returns a real `404` for an unknown session ID**, rather than silently returning an empty message list indistinguishable from a legitimately empty new session. This was raised as an open design question mid-phase and resolved deliberately rather than left as an ambiguous default.

## Results

- **A significant methodology finding, caught by the project's own verification discipline**: `TestClient` only runs `lifespan` startup/shutdown when used as a context manager (`with TestClient(app) as client:`), not from a bare `TestClient(app)` instantiation. An early "passing" health check was actually a false positive — `lifespan` never ran, but the simplistic health handler at the time never touched `app.state`, so the test had no way to reveal the gap. This was caught specifically because `/health` was later upgraded to check real dependency state, which immediately surfaced an `AttributeError` that a weaker test would have hidden indefinitely. This is treated as a genuine, valuable finding: a health check (or any test) is only as good as what it actually touches, not what it appears to check.
- **A real integration gap in Phase 16's original design was found and fixed while wiring `/chat`.** `generate_answer_with_memory()` originally returned only the answer string and expected citations to be supplied *before* the call — but citations (Phase 15) can only be built from the retrieved results, which exist only *inside* that function call. This chicken-and-egg problem had gone unnoticed through Phase 16's own testing, since that phase never exercised the citations parameter with real data. Fixed by changing the function to return `(answer, results, assistant_message_id)` and adding a new `update_message_citations()` function, so citations attach to the already-stored assistant message as a deliberate, separate post-generation step.
- **Full end-to-end verification through the real API**, not just individual endpoints in isolation: a session was created, a first message correctly answered with three properly-resolved citations spanning both OpenFDA and WHO sources (including a correct, real WHO URL), and — critically — the exact reformulation follow-up case from Phase 16 ("What are its contraindications?", with no drug name repeated) was correctly resolved and cited through the actual HTTP layer, not just the underlying function. This confirms every subsystem built across Phases 8-17 now genuinely works together as one system, reachable over HTTP.
- **Verified as a real running server**, not only via `TestClient`: a live `uvicorn` process, hit with a real `curl` request, correctly returned `200 OK` with all three dependencies healthy.

## Challenges & Solutions

- **A path-resolution issue specific to how `main.py` can be launched.** Unlike the `run_*.py` scripts (which have one single, well-understood invocation convention), `main.py` can be started multiple different ways — `uvicorn --app-dir`, imported by `TestClient`, run directly — each with different default `sys.path` contents. The original fix (a `find_project_root()`-anchored path insertion) was placed *after* the `from config.settings import settings` import line, meaning it never got a chance to run before that import failed under `uvicorn --app-dir`. Resolved by moving all path setup to the very top of the file, before any `config` import — the same root cause class as every prior phase's path-fragility issue, but manifesting differently here because of the app's multiple launch modes.
- **The two integration gaps described above (citations chicken-and-egg problem, `TestClient`/lifespan false positive) were both found only because this phase genuinely exercises prior phases' code together for the first time**, rather than each in isolation. This is treated as expected and valuable: integration points are exactly where gaps between independently-correct components tend to surface, and finding them here — deliberately, through real end-to-end testing — is a better outcome than finding them later in Phase 20 or in a live demo.

## Files Created

- `backend/src/medrag/api/__init__.py`
- `backend/src/medrag/api/main.py` (`lifespan`, `/health`, `/sessions` POST/GET, `/chat`)
- `backend/src/medrag/api/models.py` (all request/response Pydantic models)
- Modified `backend/src/medrag/memory/chat_memory.py`: `generate_answer_with_memory()` signature changed to return `(answer, results, assistant_message_id)`; added `session_exists()` and `update_message_citations()`

No notebook this phase (see Key Design Decisions #1). No separate runner script — the API itself, launched via `uvicorn`, is the entry point.