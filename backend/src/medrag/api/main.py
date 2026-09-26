"""
FastAPI application: exposes the MedRAG pipeline (hybrid retrieval,
reranking, generation, citations, knowledge graph, chat memory) as an
HTTP API.

Backend clients (Qdrant, Neo4j, Postgres, OpenAI) are created once at
startup via the lifespan context manager and stored on app.state, not
recreated per-request - this avoids the cost and waste of e.g. opening
a fresh Neo4j driver connection on every single API call.

Deliberately out of scope for this phase: authentication and rate
limiting. Reasonable for a portfolio project without public production
traffic; a stated, documented boundary rather than an oversight.
"""

import sys
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

from config.settings import settings
from medrag.embeddings.qdrant_client import get_qdrant_client
from medrag.memory.db import get_postgres_connection, ensure_schema
from medrag.memory.chat_memory import (
    create_session,
    get_session_history,
    session_exists,
    get_session_user_id,  # Phase 19
    generate_answer_with_memory,
    update_message_citations,
)
from medrag.citations.citations import build_who_source_url_lookup, build_citations

# Phase 19
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
    UploadDocumentResponse,  # Phase 19
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("medrag.api")


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

    app.state.pg_conn = get_postgres_connection(
        settings.postgres_host, settings.postgres_port,
        settings.postgres_db, settings.postgres_user, settings.postgres_password,
    )
    ensure_schema(app.state.pg_conn)
    logger.info("  Postgres connected")

    app.state.openai_client = openai.OpenAI(api_key=settings.openai_api_key)
    logger.info("  OpenAI client ready")

    who_raw_dir = str(PROJECT_ROOT / "data" / "raw" / "who")
    app.state.who_source_urls = build_who_source_url_lookup(who_raw_dir)
    logger.info(f"  Loaded {len(app.state.who_source_urls)} WHO source URLs")

    yield

    logger.info("Shutting down - closing backend connections...")
    app.state.neo4j_driver.close()
    app.state.pg_conn.close()


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
        with state.pg_conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception as e:
        deps["postgres"] = f"error: {e}"

    overall = "ok" if all(v == "ok" for v in deps.values()) else "degraded"
    return HealthResponse(status=overall, dependencies=DependencyStatus(**deps))


@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session_endpoint(payload: CreateSessionRequest, request: Request):
    # Phase 19: user_id passed through so this session can share
    # upload access with any other session belonging to the same user
    session_id = create_session(
        request.app.state.pg_conn, title=payload.title, user_id=payload.user_id
    )
    return CreateSessionResponse(session_id=session_id)


@app.get("/sessions/{session_id}", response_model=SessionHistoryResponse)
async def get_session_endpoint(session_id: str, request: Request):
    conn = request.app.state.pg_conn
    if not session_exists(conn, session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    messages = get_session_history(conn, session_id)
    return SessionHistoryResponse(
        session_id=session_id,
        messages=[MessageOut(**m) for m in messages],
    )


# Phase 19: new endpoint - accepts a PDF upload for a given session,
# extracts/chunks/embeds/upserts it under that session's user_id.
@app.post("/sessions/{session_id}/documents", response_model=UploadDocumentResponse)
async def upload_document_endpoint(session_id: str, request: Request, file: UploadFile = File(...)):
    conn = request.app.state.pg_conn

    if not session_exists(conn, session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    user_id = get_session_user_id(conn, session_id)
    if user_id is None:
        # Upload isolation requires a user_id - a session created
        # without one has no way to scope who can later retrieve this
        # document, so we refuse rather than silently upload it unscoped.
        raise HTTPException(
            status_code=400,
            detail="This session has no user_id. Create a session with a user_id to enable document uploads.",
        )

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
        user_id=user_id,
        session_id=session_id,
        document_id=document_id,
        filename=file.filename,
    )
    chunk_count = embed_and_upsert_upload_chunks(
        chunks, request.app.state.qdrant_client, request.app.state.openai_client
    )

    return UploadDocumentResponse(
        document_id=document_id, filename=file.filename, chunk_count=chunk_count
    )


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
    upfront."""
    state = request.app.state

    if not session_exists(state.pg_conn, payload.session_id):
        raise HTTPException(status_code=404, detail=f"Session '{payload.session_id}' not found")

    # Phase 19: look up this session's user_id so uploaded documents
    # (if any) are actually retrievable during chat, not just at upload time
    user_id = get_session_user_id(state.pg_conn, payload.session_id)

    answer, results, assistant_message_id = generate_answer_with_memory(
        payload.message,
        payload.session_id,
        state.pg_conn,
        qdrant_client=state.qdrant_client,
        openai_client=state.openai_client,
        neo4j_driver=state.neo4j_driver,
        user_id=user_id,
    )

    citations = build_citations(answer, results, state.who_source_urls)
    update_message_citations(state.pg_conn, assistant_message_id, citations)

    return ChatResponse(answer=answer, citations=citations)