"""
Postgres connection and schema management for MedRAG's chat memory.

Runs in its own dedicated Postgres container/database (medrag_chat, on
host port 5433) - deliberately isolated from any other project's
database.

Concurrency note (Phase 20 fix): originally this module handed out one
single psycopg2 connection, created once at API startup and reused for
every request via app.state.pg_conn. That was safe only because the
API's routes were, until a separate fix, effectively blocking/serial -
once /chat's pipeline was moved onto a worker thread (via
starlette.concurrency.run_in_threadpool) so it wouldn't freeze the
event loop, it became possible for two threads to touch that same
single connection at genuinely the same time. psycopg2 connections are
NOT safe for concurrent use across threads, so this was a real, latent
correctness bug even though it hadn't yet caused a visible failure.

Fix: use psycopg2.pool.ThreadedConnectionPool instead of one shared
connection. Each request now checks out its own connection for the
duration of that request (see main.py's get_conn() context manager)
and returns it when done, instead of every request sharing one
connection object across threads.
"""

import logging
import hashlib
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
from psycopg2.extensions import connection as PGConnection

logger = logging.getLogger("medrag.memory")

CREATE_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Account ownership groups chats for listing and authorization. Upload retrieval
-- remains scoped to the individual session ID; other chats do not share uploads.
-- Older rows with user_id NULL are not implicitly assigned to a signed-in account.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);

CREATE TABLE IF NOT EXISTS messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    citations JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, created_at);

-- A stable tie-breaker for messages written in a single transaction.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_sequence BIGSERIAL;
ALTER TABLE messages ALTER COLUMN created_at SET DEFAULT clock_timestamp();

CREATE TABLE IF NOT EXISTS uploaded_documents (
    document_id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    filename TEXT NOT NULL,
    chunk_count INTEGER NOT NULL CHECK (chunk_count > 0),
    UNIQUE (session_id, content_hash)
);

CREATE TABLE IF NOT EXISTS accounts (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES accounts(user_id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS request_limits (
    bucket_key TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    attempts INTEGER NOT NULL,
    PRIMARY KEY (bucket_key, window_start)
);
"""


@contextmanager
def transaction(conn):
    """Commit a complete operation or roll it back; respect an outer transaction."""
    if not conn.autocommit:
        yield conn
        return
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


@contextmanager
def session_operation(conn, session_id):
    """Serialize one session across processes using a connection-scoped lock.

    The session lock also covers slow external calls, without keeping a SQL
    transaction open. Different sessions use different keys and run concurrently.
    """
    key = int.from_bytes(hashlib.sha256(str(session_id).encode()).digest()[:8], "big", signed=True)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (key,))
    try:
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (key,))


def get_postgres_connection(host: str, port: int, dbname: str, user: str, password: str) -> PGConnection:
    """Kept for any script/notebook still using a single direct
    connection (e.g. one-off verification scripts). The live API no
    longer uses this - see get_postgres_pool() below."""
    conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)
    conn.autocommit = True
    return conn


def get_postgres_pool(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
    minconn: int = 1,
    maxconn: int = 10,
) -> psycopg2.pool.ThreadedConnectionPool:
    """Create a thread-safe connection pool. minconn/maxconn=1/10 is a
    reasonable default for a portfolio project's traffic level (not
    tuned against real concurrent load, which this project doesn't
    have) - raise maxconn if request volume ever actually requires
    it."""
    return psycopg2.pool.ThreadedConnectionPool(
        minconn, maxconn, host=host, port=port, dbname=dbname, user=user, password=password
    )


def ensure_schema(conn: PGConnection) -> None:
    """Create/migrate the sessions/messages schema. Safe to call
    repeatedly - IF NOT EXISTS and ADD COLUMN IF NOT EXISTS make this
    idempotent, matching the non-destructive pattern used for
    ensure_collections() (Qdrant) and setup_constraints() (Neo4j)."""
    with conn.cursor() as cur:
        cur.execute(CREATE_SCHEMA_SQL)
    logger.info("Chat memory schema ensured (sessions with user_id, messages)")


def ensure_schema_via_pool(pool: psycopg2.pool.ThreadedConnectionPool) -> None:
    """Run ensure_schema() using a connection checked out from the
    pool, for use during lifespan startup (which now creates a pool,
    not a single connection)."""
    conn = pool.getconn()
    try:
        conn.autocommit = True
        ensure_schema(conn)
    finally:
        pool.putconn(conn)
