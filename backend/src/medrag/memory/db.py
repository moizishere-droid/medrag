"""
Postgres connection and schema management for MedRAG's chat memory.

Runs in its own dedicated Postgres container/database (medrag_chat, on
host port 5433) - deliberately isolated from any other project's
database (e.g. a separate loan-risk-system Postgres instance running
on the default 5432), so the two portfolio projects never share state.
"""

import logging

import psycopg2
from psycopg2.extensions import connection as PGConnection

logger = logging.getLogger("medrag.memory")

CREATE_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
    """Connect to Postgres with autocommit enabled - chat memory writes
    (creating a session, appending a message) are simple, independent
    operations that don't need explicit transaction boundaries around
    them in this module; autocommit keeps the calling code simple."""
    conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)
    conn.autocommit = True
    return conn


def ensure_schema(conn: PGConnection) -> None:
    """Create the sessions/messages tables and supporting index if they
    don't already exist. Safe to call repeatedly - IF NOT EXISTS makes
    this idempotent, matching the non-destructive pattern already used
    for ensure_collections() (Qdrant) and setup_constraints() (Neo4j)."""
    with conn.cursor() as cur:
        cur.execute(CREATE_SCHEMA_SQL)
    logger.info("Chat memory schema ensured (sessions, messages)")