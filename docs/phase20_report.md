# Phase 20: Streamlit Frontend

## Objective

Build a working chat interface on top of the Phase 18 FastAPI backend: a
session-aware chat UI, a session switcher, and a per-session document
uploader (Phase 19's upload pipeline), so the full MedRAG system is usable
end-to-end through a browser rather than only via curl/TestClient.

## What Was Built

A single-file Streamlit app (`streamlit_app.py`, project root) with four
pieces, built and verified incrementally:

1. **Health check** — sidebar indicator calling `GET /health`, parsing the
   flat `{qdrant, neo4j, postgres: "ok"}` dependency status shape.
2. **Session switcher** — sidebar dropdown backed by a new `GET /sessions`
   endpoint (added as a Phase 20 prerequisite), plus a "New Session" button
   wired to `POST /sessions`. Switching sessions loads that session's full
   history via `GET /sessions/{id}`.
3. **Chat interface** — renders `st.session_state.messages` via
   `st.chat_message`, with citations shown in an `st.expander`; `st.chat_input`
   wired to `POST /chat` with a 60s timeout (generation pipeline is multi-step
   and genuinely slow).
4. **File uploader** — `st.sidebar.file_uploader` scoped to the current
   session, calling `POST /sessions/{session_id}/documents`. Guarded against
   Streamlit's rerun model re-submitting the same file on every subsequent
   rerun by tracking a `(session_id, file_id)` key in `session_state`.

Verified end-to-end: uploading a PDF and asking a question about it produces
an answer correctly citing both the original curated corpus (WHO) and the
freshly uploaded document (`user_upload`) in the same response.

## Key Design Decisions

- **Single-file app, not split into modules.** Streamlit's rerun-the-whole-
  script model doesn't benefit from module boundaries the way a typical app
  does; one file matches how Streamlit actually executes.
- **No client-side identity/persistence layer.** Per Phase 19's finalized
  session-scoped upload design, there's no user_id/login concept — sessions
  are addressed purely by `session_id`, so no browser storage or auth was
  needed for isolation to work correctly.
- **Scratch-script build, not notebook cells** — same exception as Phase 18's
  FastAPI: a long-running interactive app doesn't fit `.ipynb` cell-by-cell
  execution. Verified via direct browser interaction instead.
- **Added `GET /sessions`** as a prerequisite endpoint (not originally in the
  Phase 18 endpoint list) — the session switcher has no other way to
  discover existing sessions to list.

## Results

All four pieces work correctly and were verified live in the browser,
including:
- Correct session isolation (switching sessions loads the right, distinct
  history)
- Correct multi-source citation rendering on a single answer (WHO + a
  user-uploaded PDF, both linked and titled correctly)
- Correct behavior under concurrent load (verified directly — see Challenges)

## Challenges & Solutions

This phase surfaced two significant, genuinely valuable findings beyond
routine UI-building — both are documented here in full because they're real
production-readiness lessons, not just bugs fixed along the way.

### 1. Event-loop blocking + unsafe shared connection (backend concurrency bug)

**Found:** Testing revealed that a concurrent `GET /sessions` request would
hang for the entire duration of an in-flight `POST /chat` request, even
though the server process was alive and otherwise idle. Root cause: every
route in `main.py` was declared `async def`, but the actual pipeline work
underneath — `psycopg2`, the Neo4j driver, the Qdrant client, and
`openai.OpenAI()` (the synchronous client, not `AsyncOpenAI`) — are all
blocking, non-async-native clients. Calling them directly inside an `async
def` route with no `await` freezes uvicorn's single event loop thread for
the entire call, which was invisible under Phase 18's TestClient-based
testing (that testing never actually exercised true concurrent requests).

**Fixed, Part 1:** Wrapped the two genuinely slow, blocking pipeline calls
(`generate_answer_with_memory` in `/chat`, `embed_and_upsert_upload_chunks`
in `/documents`) in `starlette.concurrency.run_in_threadpool`, moving them
onto worker threads so the event loop stays free to serve other requests.
Verified by reproducing the original hang, then confirming a concurrent
`/sessions` request now returns instantly while `/chat` is still "Thinking".

**Found (Part 2, a gap Part 1 itself opened):** Once the blocking pipeline
call could genuinely run on a worker thread concurrently with other
requests, the single shared `app.state.pg_conn` — one `psycopg2` connection,
created once at startup and reused by every request — became a real, latent
thread-safety bug: `psycopg2` connections are not safe for concurrent use
across threads. This had never manifested visibly, because before Part 1's
fix, the event-loop blocking meant only one request could ever be "in
flight" at a time anyway.

**Fixed, Part 2:** Replaced the single shared connection with
`psycopg2.pool.ThreadedConnectionPool`. Each request now checks out its own
connection for its duration via a `get_conn()` context manager and returns
it when done, instead of every request/thread sharing one connection
object. Verified via a corrected startup log line ("Postgres connected
(pool ready)") and by re-running the full concurrency test on the
pool-based code.

### 2. Streamlit version bug + cascading dependency-compatibility break

**Found:** An intermittent `Bad message format: Cannot read properties of
undefined (reading 'setIn')` frontend crash appeared, initially suspected to
be caused by a real app-level bug (duplicate session labels in the
selectbox — a genuine, separate bug that was found and fixed: resolving a
selection via `labels.index(selected_label)` silently returns the *first*
session sharing that label, both a correctness bug and a plausible trigger
for this exact class of Streamlit error). After fixing that, the crash still
recurred on plain page load with no interaction at all — ruling out an
app-level cause.

Web research confirmed this specific error is a long-standing, recurring
Streamlit bug (present across many historical versions, tied to
frontend/backend element-tree state desync), and the installed version
(`streamlit==1.35.0`) was roughly two years out of date relative to the
project's actual timeline.

**Fixed:** Upgraded `streamlit` (1.35.0 → 1.64.0). This resolved the crash,
but the upgrade pulled in a newer `starlette` as a transitive dependency,
which broke the installed `fastapi` version (`Router.__init__() got an
unexpected keyword argument 'on_startup'` — a real, hard startup failure).
Resolved by upgrading `fastapi` (0.111.0 → 0.142.1) and `uvicorn` (0.29.0 →
0.54.0) together with the new `starlette` (1.7.0) as a confirmed-compatible
trio, now explicitly pinned together in `requirements.txt` with a comment
warning against bumping any one of the three in isolation without
re-verifying startup.

A secondary, unrelated snag during this upgrade: a Windows file-lock
(`WinError 32`) prevented `pip` from replacing `uvicorn.exe` because the
running backend process itself still held the file open — resolved by
fully terminating the backend process before retrying the upgrade.

### 3. Requirements file drift (found during the above fix)

While resolving the above, discovered the project had two separate
`requirements.txt` files (`backend/requirements.txt`, the real/maintained
one, and a stale, effectively unused `frontend/requirements.txt` with an
unpinned `streamlit` and an outdated `pillow==10.3.0` pin that didn't match
what was actually installed). Consolidated into a single
`backend/requirements.txt` covering both the backend and the Streamlit
frontend script (they run in one shared venv in practice), and deleted the
unused `frontend/requirements.txt` plus a scratch `pip freeze` diffing file.
Same discipline as the post-Phase 18 audit: verify against a real `pip
freeze`, don't trust memory of what should be pinned.

## Files Created / Modified

- `streamlit_app.py` (new, project root) — the full four-piece Streamlit app
- `backend/src/medrag/api/main.py` — added `GET /sessions`; wrapped the two
  blocking pipeline calls in `run_in_threadpool`; replaced the single shared
  Postgres connection with a pool-backed `get_conn()` context manager used
  by every route
- `backend/src/medrag/memory/db.py` — added `get_postgres_pool()` and
  `ensure_schema_via_pool()` (kept `get_postgres_connection()` for any
  single-connection script use)
- `backend/src/medrag/api/models.py` — added `SessionSummary`,
  `SessionListResponse`
- `backend/src/medrag/memory/chat_memory.py` — added `list_sessions()`
- `backend/requirements.txt` — consolidated (absorbed the frontend
  dependency set), updated `fastapi`/`starlette`/`uvicorn` to a confirmed-
  compatible trio, added `streamlit==1.64.0`
- `frontend/requirements.txt` — deleted (stale, unused)