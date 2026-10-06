"""
FastAPI application: exposes the MedRAG pipeline (hybrid retrieval,
reranking, generation, citations, knowledge graph, chat memory) as an
HTTP API.

Backend clients (Qdrant, Neo4j, OpenAI) are created once at startup via
the lifespan context manager and stored on app.state, not recreated
per-request - this avoids the cost and waste of e.g. opening a fresh
Neo4j driver connection on every single API call.

Authentication is required by default: revocable bearer tokens, account-owned
sessions and shared database-backed request limits protect private routes.
Disabling authentication is supported only for local development clients.

Isolation model (revised): uploaded documents are scoped to the
session_id they were uploaded in, not a separate user_id concept. A
session's own uploads are visible only within that same session;
opening a new session starts with no access to any prior session's
uploads. This is a deliberate simplification over an earlier
multi-session-per-user design - see docs/phase19_report.md for the
full history of that design change.

Concurrency: synchronous routes run in FastAPI worker threads. The async
upload route offloads database checks, extraction, chunking and indexing
to worker threads. Each request checks out a distinct pooled PostgreSQL
connection; pool exhaustion returns a temporary-unavailable response.
"""

import sys
from contextlib import contextmanager, ExitStack
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
from time import perf_counter
from contextlib import asynccontextmanager

import openai
from psycopg2.pool import PoolError
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Depends
from psycopg2.errors import UniqueViolation
from medrag.api import auth
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase
from starlette.concurrency import run_in_threadpool

from config.settings import settings
from medrag.embeddings.qdrant_client import get_qdrant_client
from medrag.memory.db import get_postgres_pool, ensure_schema_via_pool, session_operation, transaction
from medrag.retrieval.reranking import warmup_retrieval
from medrag.generation.language import AnswerLanguageError
from fastapi.responses import JSONResponse
from medrag.memory.chat_memory import (
    create_session,
    get_session_history,
    list_sessions,
    session_exists,
    generate_answer_with_memory,
    update_message_citations,
    title_session_from_first_query,
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
from medrag.ingestion import user_upload

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
    Credentials,
    TokenResponse,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("medrag.api")


@contextmanager
def get_conn(app: FastAPI):
    """Check out one connection from the pool for the duration of a
    single request, and always return it - even if the request raises.
    Replaces the old pattern of reaching for one shared, long-lived
    app.state.pg_conn directly."""
    try:
        conn = app.state.pg_pool.getconn()
    except PoolError as exc:
        raise HTTPException(status_code=503, detail="Database is busy. Please retry.", headers={"Retry-After": "1"}) from exc
    try:
        conn.autocommit = True
        yield conn
    finally:
        app.state.pg_pool.putconn(conn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with ExitStack() as resources:
        logger.info("Starting up - connecting to backend services...")

        app.state.qdrant_client = get_qdrant_client(settings.qdrant_url or "http://localhost:6333")
        resources.callback(getattr(app.state.qdrant_client, "close", lambda: None))
        app.state.qdrant_client.get_collections()  # fail fast if unreachable
        logger.info("  Qdrant connected")

        app.state.neo4j_driver = GraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )
        resources.callback(app.state.neo4j_driver.close)
        app.state.neo4j_driver.verify_connectivity()
        logger.info("  Neo4j connected")

        app.state.pg_pool = get_postgres_pool(
            settings.postgres_host, settings.postgres_port,
            settings.postgres_db, settings.postgres_user, settings.postgres_password,
        )
        resources.callback(app.state.pg_pool.closeall)
        ensure_schema_via_pool(app.state.pg_pool)
        logger.info("  Postgres connected (pool ready)")

        app.state.openai_client = openai.OpenAI(api_key=settings.openai_api_key)
        resources.callback(getattr(app.state.openai_client, "close", lambda: None))
        logger.info("  OpenAI client ready")

        who_raw_dir = str(PROJECT_ROOT / "data" / "raw" / "who")
        app.state.who_source_urls = build_who_source_url_lookup(who_raw_dir)
        logger.info(f"  Loaded {len(app.state.who_source_urls)} WHO source URLs")

        if settings.retrieval_warmup:
            logger.info("  Warming retrieval models before serving requests...")
            await run_in_threadpool(warmup_retrieval)
            logger.info("  Retrieval models ready")

        yield



app = FastAPI(title="MedRAG API", lifespan=lifespan)


@app.exception_handler(AnswerLanguageError)
async def answer_language_error(request, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_identity(request: Request):
    if not settings.auth_required:
        if request.client and request.client.host not in {"127.0.0.1", "::1", "localhost", "testclient", "test", "testserver"}:
            raise HTTPException(status_code=403, detail="Local-only mode rejects remote clients.")
        return None
    with get_conn(request.app) as conn:
        host = request.client.host if request.client else "unknown"
        auth.rate_limit(conn, f"api-ip:{host}", 120)
        authorization = request.headers.get("Authorization")
        if not authorization and request.cookies.get(auth.SESSION_COOKIE):
            origin = request.headers.get("Origin")
            if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in settings.cors_origins:
                raise HTTPException(status_code=403, detail="Untrusted browser origin.")
            authorization = f"Bearer {request.cookies[auth.SESSION_COOKIE]}"
        identity = auth.token_owner(conn, authorization)
        budget = 10 if request.url.path == "/chat" else 5 if request.url.path.endswith("/documents") else 120
        group = "chat" if request.url.path == "/chat" else "upload" if request.url.path.endswith("/documents") else "read"
        auth.rate_limit(conn, f"{group}:{identity}", budget)
        return identity


def check_owned_session(conn, session_id, identity):
    exists = session_exists(conn, session_id) if identity is None else auth.owns_session(conn, session_id, identity)
    if not exists:
        raise HTTPException(status_code=404, detail="Session not found")


@app.get("/auth/config")
def auth_config():
    return {"required": settings.auth_required}


@app.post("/auth/register", response_model=TokenResponse)
def register(payload: Credentials, request: Request, response: Response):
    with get_conn(request.app) as conn:
        auth.rate_limit(conn, f"login:{request.client.host if request.client else 'unknown'}", 5)
        digest = auth.password_hash(payload.password)
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO accounts (username, password_hash) VALUES (%s, %s) RETURNING user_id", (payload.username, digest))
                user_id = cur.fetchone()[0]
        except UniqueViolation as exc:
            raise HTTPException(status_code=409, detail="Username unavailable.") from exc
        token = auth.issue_token(conn, user_id, settings.auth_token_hours)
        auth.set_session_cookie(response, token, settings.auth_token_hours, settings.auth_cookie_secure)
        return TokenResponse(access_token=token)


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: Credentials, request: Request, response: Response):
    with get_conn(request.app) as conn:
        auth.rate_limit(conn, f"login:{request.client.host if request.client else 'unknown'}", 5)
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, password_hash FROM accounts WHERE username = %s", (payload.username,))
            row = cur.fetchone()
        # Hash unknown-account attempts too, avoiding an obvious timing shortcut.
        valid = auth.password_matches(payload.password, row[1]) if row else bool(auth.password_hash(payload.password)) and False
        if not valid:
            raise HTTPException(status_code=401, detail="Incorrect username or password.")
        token = auth.issue_token(conn, row[0], settings.auth_token_hours)
        auth.set_session_cookie(response, token, settings.auth_token_hours, settings.auth_cookie_secure)
        return TokenResponse(access_token=token)


@app.post("/auth/logout")
def logout(request: Request, response: Response, identity=Depends(get_identity)):
    import hashlib
    token = auth.request_token(request)
    with get_conn(request.app) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM auth_tokens WHERE token_hash = %s", (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie(auth.SESSION_COOKIE, path="/", secure=settings.auth_cookie_secure, httponly=True, samesite="lax")
    return {"status": "signed_out"}


@app.get("/health", response_model=HealthResponse)
def health(request: Request):
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
def create_session_endpoint(payload: CreateSessionRequest, request: Request, identity=Depends(get_identity)):
    with get_conn(request.app) as conn:
        session_id = create_session(conn, title=payload.title, user_id=identity)
    return CreateSessionResponse(session_id=session_id)


@app.get("/sessions/{session_id}", response_model=SessionHistoryResponse)
def get_session_endpoint(session_id: uuid.UUID, request: Request, identity=Depends(get_identity)):
    session_id = str(session_id)
    with get_conn(request.app) as conn:
        check_owned_session(conn, session_id, identity)
        messages = get_session_history(conn, session_id)

    return SessionHistoryResponse(
        session_id=session_id,
        messages=[MessageOut(**m) for m in messages],
    )


@app.post("/sessions/{session_id}/documents", response_model=UploadDocumentResponse)
async def upload_document_endpoint(session_id: uuid.UUID, request: Request, file: UploadFile = File(...), identity=Depends(get_identity)):
    """Uploads are scoped to session_id directly - the session a
    document is uploaded in is the only session that can retrieve it.
    No separate user_id concept; see module docstring."""
    session_id = str(session_id)
    def check_session():
        with get_conn(request.app) as conn:
            check_owned_session(conn, session_id, identity)
    await run_in_threadpool(check_session)

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_bytes = await file.read(user_upload.MAX_FILE_SIZE_BYTES + 1)

    try:
        validate_upload_size(file_bytes)
    except UploadTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))

    filename = file.filename or "Uploaded document.pdf"
    def index_upload():
        with get_conn(request.app) as conn, session_operation(conn, session_id):
            check_owned_session(conn, session_id, identity)
            return user_upload.index_document(conn, session_id, file_bytes, filename,
                                              request.app.state.qdrant_client,
                                              request.app.state.openai_client)
    try:
        result = await run_in_threadpool(index_upload)
    except UploadExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return UploadDocumentResponse(**result)


@app.get("/sessions", response_model=SessionListResponse)
def list_sessions_endpoint(request: Request, identity=Depends(get_identity)):
    with get_conn(request.app) as conn:
        sessions = list_sessions(conn) if identity is None else list_sessions(conn, user_id=identity)
    return SessionListResponse(sessions=sessions)


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(payload: ChatRequest, request: Request, identity=Depends(get_identity)):
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
    request's full duration (including generation) -
    generate_answer_with_memory() internally does several sequential
    queries against the same conn (reformulation history lookup,
    message inserts, etc.) that all need to see a single consistent
    connection, not one newly checked-out connection per internal
    call."""
    state = request.app.state
    started = perf_counter()

    with get_conn(request.app) as conn, session_operation(conn, payload.session_id), transaction(conn):
        check_owned_session(conn, payload.session_id, identity)
        title_session_from_first_query(conn, payload.session_id, payload.message)

        # Blocking (two sequential OpenAI calls + cross-encoder rerank +
        # Postgres/Neo4j/Qdrant I/O) - offloaded to a worker thread so it
        # doesn't freeze the event loop for other requests (this is what
        # was causing concurrent /health and /sessions calls to hang).
        answer, results, assistant_message_id = generate_answer_with_memory(
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

    logger.info("Chat request completed in %.3f seconds", perf_counter() - started)
    return ChatResponse(answer=answer, citations=citations)
