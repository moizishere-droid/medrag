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

-- Phase 19: user_id added to support multi-chat-per-user grouping (a
-- user with several open chats can share uploaded-document access
-- across all of them). ADD COLUMN IF NOT EXISTS keeps this migration
-- safe to run against a database created before this column existed -
-- existing session rows simply get user_id = NULL, meaning they
-- belong to no particular user (they still work, just without shared
-- upload access across other sessions).
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
"""


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