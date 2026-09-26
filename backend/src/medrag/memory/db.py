"""
Postgres connection and schema management for MedRAG's chat memory.

Runs in its own dedicated Postgres container/database (medrag_chat, on
host port 5433) - deliberately isolated from any other project's
database.
"""

import logging

import psycopg2
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
    conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)
    conn.autocommit = True
    return conn


def ensure_schema(conn: PGConnection) -> None:
    """Create/migrate the sessions/messages schema. Safe to call
    repeatedly - IF NOT EXISTS and ADD COLUMN IF NOT EXISTS make this
    idempotent, matching the non-destructive pattern used for
    ensure_collections() (Qdrant) and setup_constraints() (Neo4j)."""
    with conn.cursor() as cur:
        cur.execute(CREATE_SCHEMA_SQL)
    logger.info("Chat memory schema ensured (sessions with user_id, messages)")