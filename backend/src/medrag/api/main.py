"""
FastAPI application: exposes the MedRAG pipeline (hybrid retrieval,
reranking, generation, citations, knowledge graph, chat memory) as an
HTTP API.

Backend clients (Qdrant, Neo4j, OpenAI) are created once at startup via
the lifespan context manager and stored on app.state, not recreated
per-request - this avoids the cost and waste of e.g. opening a fresh
Neo4j driver connection on every single API call.

Deliberately out of scope for this phase: authentication and rate
limiting. Reasonable for a portfolio project without public production
traffic; a stated, documented boundary rather than an oversight.

Isolation model (revised): uploaded documents are scoped to the
session_id they were uploaded in, not a separate user_id concept. A
session's own uploads are visible only within that same session;
opening a new session starts with no access to any prior session's
uploads. This is a deliberate simplification over an earlier
multi-session-per-user design - see docs/phase19_report.md for the
full history of that design change.

Concurrency fix (Phase 20, two-part):

Part 1 - event loop blocking: every route here is declared async def,
but the actual pipeline work underneath (psycopg2, the Neo4j driver,
the Qdrant client, and openai.OpenAI()) are all SYNCHRONOUS/blocking
clients, not async-native ones. Calling them directly inside an async
def route with no await freezes uvicorn's single event loop for the
entire duration of that call - confirmed live: a slow /chat request
caused a concurrent /sessions request to hang until /chat finished,
even though the server process itself was alive and idle from the OS's
point of view. Fixed by wrapping the two genuinely slow, blocking calls
(generate_answer_with_memory in /chat, embed_and_upsert_upload_chunks
in /documents) in starlette.concurrency.run_in_threadpool, so they run
on a worker thread instead of the event loop thread. Verified fixed:
/sessions now responds instantly even while a /chat request is still
"Thinking..." in Streamlit.

Part 2 - shared-connection thread safety: Part 1's fix means a
blocking pipeline call can now genuinely run on a worker thread at the
same time another request is being handled on the event loop thread
(or another worker thread). The original code held ONE single
psycopg2 connection (app.state.pg_conn), created once at startup and
reused by every request - psycopg2 connections are not safe for
concurrent use across threads, so this became a real (if not yet
visibly triggered) correctness bug the moment Part 1 landed. Fixed by
replacing the single connection with a psycopg2.pool.ThreadedConnectionPool
(app.state.pg_pool, see db.py). Every route now checks out its own
connection via the get_conn() context manager below for the duration
of that request, and returns it to the pool when done, instead of
sharing one connection object across threads.
"""

import sys
from contextlib import contextmanager
from pathlib import Path


def find_project_root(marker: str = "backend", start: Path = None) -> Path:
    """Walk upward from this file's location until a folder containing
    `marker` is found. main.py can be launched several different ways
    (uvicorn with --app-dir, imported as a package by TestClient, run
    directly) with different working directories and different default
    sys.path entries each time - none of them reliably include
    backend/ itself, which is where config/ (a plain folder, not an
    installed package) lives. This must run and modify sys.path BEFORE
    any `from config...` import below, not after - the exact ordering
    mistake that caused this to fail under uvicorn --app-dir despite
    working fine under TestClient (which happened to already have
    backend/ on sys.path from the verify script's own setup)."""
    current = (start or Path(__file__).resolve()).parent
    for candidate in [current, *current.parents]:
        if (candidate / marker).is_dir():
            return candidate
    raise RuntimeError(f"Could not find a '{marker}' folder above {current}")


PROJECT_ROOT = find_project_root()
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import logging
import uuid
from contextlib import asynccontextmanager

import openai
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase
from starlette.concurrency import run_in_threadpool

from config.settings import settings
from medrag.embeddings.qdrant_client import get_qdrant_client
from medrag.memory.db import get_postgres_pool, ensure_schema_via_pool
from medrag.memory.chat_memory import (
    create_session,
    get_session_history,
    list_sessions,
    session_exists,
    generate_answer_with_memory,
    update_message_citations,
)
from medrag.citations.citations import build_who_source_url_lookup, build_citations

from medrag.ingestion.user_upload import (
    validate_upload_size,
    extract_text_from_pdf,
    chunk_user_upload,
    embed_and_upsert_upload_chunks,
    UploadTooLargeError,
    UploadExtractionError,
)

from medrag.api.models import (
    CreateSessionRequest,
    CreateSessionResponse,
    SessionHistoryResponse,
    MessageOut,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    DependencyStatus,
    SessionListResponse,
    UploadDocumentResponse,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("medrag.api")


@contextmanager
def get_conn(app: FastAPI):
    """Check out one connection from the pool for the duration of a
    single request, and always return it - even if the request raises.
    Replaces the old pattern of reaching for one shared, long-lived
    app.state.pg_conn directly."""
    conn = app.state.pg_pool.getconn()
    conn.autocommit = True
    try:
        yield conn
    finally:
        app.state.pg_pool.putconn(conn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up - connecting to backend services...")

    app.state.qdrant_client = get_qdrant_client(settings.qdrant_url or "http://localhost:6333")
    app.state.qdrant_client.get_collections()  # fail fast if unreachable
    logger.info("  Qdrant connected")

    app.state.neo4j_driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    app.state.neo4j_driver.verify_connectivity()
    logger.info("  Neo4j connected")

    app.state.pg_pool = get_postgres_pool(
        settings.postgres_host, settings.postgres_port,
        settings.postgres_db, settings.postgres_user, settings.postgres_password,
    )
    ensure_schema_via_pool(app.state.pg_pool)
    logger.info("  Postgres connected (pool ready)")

    app.state.openai_client = openai.OpenAI(api_key=settings.openai_api_key)
    logger.info("  OpenAI client ready")

    who_raw_dir = str(PROJECT_ROOT / "data" / "raw" / "who")
    app.state.who_source_urls = build_who_source_url_lookup(who_raw_dir)
    logger.info(f"  Loaded {len(app.state.who_source_urls)} WHO source URLs")

    yield

    logger.info("Shutting down - closing backend connections...")
    app.state.neo4j_driver.close()
    app.state.pg_pool.closeall()


app = FastAPI(title="MedRAG API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Phase 20's Streamlit origin isn't known yet; tighten later
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health(request: Request):
    """Checks each backend dependency individually rather than
    returning a bare boolean - distinguishes 'the app process is
    running' from 'the app can actually serve a real request', which
    matters once Phase 22/23 deployment needs to tell those apart."""
    state = request.app.state
    deps = {"qdrant": "ok", "neo4j": "ok", "postgres": "ok"}

    try:
        state.qdrant_client.get_collections()
    except Exception as e:
        deps["qdrant"] = f"error: {e}"

    try:
        state.neo4j_driver.verify_connectivity()
    except Exception as e:
        deps["neo4j"] = f"error: {e}"

    try:
        with get_conn(request.app) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as e:
        deps["postgres"] = f"error: {e}"

    overall = "ok" if all(v == "ok" for v in deps.values()) else "degraded"
    return HealthResponse(status=overall, dependencies=DependencyStatus(**deps))


@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session_endpoint(payload: CreateSessionRequest, request: Request):
    with get_conn(request.app) as conn:
        session_id = create_session(conn, title=payload.title)
    return CreateSessionResponse(session_id=session_id)


@app.get("/sessions/{session_id}", response_model=SessionHistoryResponse)
async def get_session_endpoint(session_id: str, request: Request):
    with get_conn(request.app) as conn:
        if not session_exists(conn, session_id):
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        messages = get_session_history(conn, session_id)

    return SessionHistoryResponse(
        session_id=session_id,
        messages=[MessageOut(**m) for m in messages],
    )


@app.post("/sessions/{session_id}/documents", response_model=UploadDocumentResponse)
async def upload_document_endpoint(session_id: str, request: Request, file: UploadFile = File(...)):
    """Uploads are scoped to session_id directly - the session a
    document is uploaded in is the only session that can retrieve it.
    No separate user_id concept; see module docstring."""
    with get_conn(request.app) as conn:
        if not session_exists(conn, session_id):
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_bytes = await file.read()

    try:
        validate_upload_size(file_bytes)
    except UploadTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))

    try:
        full_text = extract_text_from_pdf(file_bytes)
    except UploadExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e))

    document_id = str(uuid.uuid4())
    chunks = chunk_user_upload(
        text=full_text,
        user_id=session_id,  # session_id IS the isolation key now
        session_id=session_id,
        document_id=document_id,
        filename=file.filename,
    )

    # Blocking (embedding + Qdrant upsert) - offloaded to a worker
    # thread so it doesn't freeze the event loop for other requests.
    chunk_count = await run_in_threadpool(
        embed_and_upsert_upload_chunks,
        chunks, request.app.state.qdrant_client, request.app.state.openai_client,
    )

    return UploadDocumentResponse(
        document_id=document_id, filename=file.filename, chunk_count=chunk_count
    )

@app.get("/sessions", response_model=SessionListResponse)
async def list_sessions_endpoint(request: Request):
    with get_conn(request.app) as conn:
        sessions = list_sessions(conn)
    return SessionListResponse(sessions=sessions)


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest, request: Request):
    """The main endpoint: runs the full history-aware pipeline (query
    reformulation -> hybrid retrieval + reranking -> knowledge graph
    enrichment -> grounded, cited, language-matching generation), then
    resolves and persists citations for the answer just generated.

    Citations can only be built after generate_answer_with_memory()
    returns (they need the retrieved results, which only exist inside
    that call) - see chat_memory.py's update_message_citations() for
    why this is a separate post-generation step rather than passed in
    upfront.

    Checks out ONE connection from the pool and holds it for this
    request's full duration (including the run_in_threadpool call) -
    generate_answer_with_memory() internally does several sequential
    queries against the same conn (reformulation history lookup,
    message inserts, etc.) that all need to see a single consistent
    connection, not one newly checked-out connection per internal
    call."""
    state = request.app.state

    with get_conn(request.app) as conn:
        if not session_exists(conn, payload.session_id):
            raise HTTPException(status_code=404, detail=f"Session '{payload.session_id}' not found")

        # Blocking (two sequential OpenAI calls + cross-encoder rerank +
        # Postgres/Neo4j/Qdrant I/O) - offloaded to a worker thread so it
        # doesn't freeze the event loop for other requests (this is what
        # was causing concurrent /health and /sessions calls to hang).
        answer, results, assistant_message_id = await run_in_threadpool(
            generate_answer_with_memory,
            payload.message,
            payload.session_id,
            conn,
            qdrant_client=state.qdrant_client,
            openai_client=state.openai_client,
            neo4j_driver=state.neo4j_driver,
            user_id=payload.session_id,  # session_id IS the isolation key now
        )

        citations = build_citations(answer, results, state.who_source_urls)
        update_message_citations(conn, assistant_message_id, citations)

    return ChatResponse(answer=answer, citations=citations)