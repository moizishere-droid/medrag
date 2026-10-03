"""Fixtures for integration tests (real Postgres / Qdrant / Neo4j).

Run with:  python -m pytest -m integration -v      (needs `docker compose up`)

Safety design: no test here can modify real data.
  * Postgres: a SEPARATE database, `medrag_chat_test`, created on demand. Tables are
    truncated before every test, and a guard asserts the connection really is the
    test database before anything destructive runs.
  * Qdrant:   a uniquely named throwaway collection (4-dim vectors), deleted afterwards.
    The module-level TEXT_COLLECTION constants are repointed to it for the test only.
  * Neo4j:    read-only queries; Community edition has no second database to use.

Qdrant location: $MEDRAG_TEST_QDRANT_URL, else QDRANT_URL from .env, else
http://localhost:6333.  The special value ":memory:" uses qdrant-client's in-process
local mode (no Docker needed; handy for a quick check, but the real server is the
meaningful target).
"""

import importlib
import os
import uuid
from types import SimpleNamespace

import psycopg2
import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from config.settings import settings
from medrag.embeddings.qdrant_client import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME

TEST_DB = "medrag_chat_test"
EMBED_DIM = 4


# --------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def pg_test_db():
    """Connection parameters for the TEST database (created and migrated once)."""
    params = {
        "host": settings.postgres_host,
        "port": settings.postgres_port,
        "user": settings.postgres_user,
        "password": settings.postgres_password,
    }
    if not all(params.values()):
        pytest.fail("Postgres settings missing (POSTGRES_HOST/PORT/USER/PASSWORD in .env)")
    assert TEST_DB != settings.postgres_db, "the test database must never be the real one"

    try:
        admin = psycopg2.connect(dbname="postgres", **params)
    except psycopg2.OperationalError as exc:
        pytest.fail(f"Cannot reach Postgres. Is `docker compose up` running? ({exc})")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{TEST_DB}"')  # constant identifier, not user input
    admin.close()

    from medrag.memory.db import ensure_schema

    conn = psycopg2.connect(dbname=TEST_DB, **params)
    conn.autocommit = True
    ensure_schema(conn)
    conn.close()
    return {**params, "dbname": TEST_DB}


@pytest.fixture
def pg_conn(pg_test_db):
    """Autocommit connection to the test DB with empty tables."""
    conn = psycopg2.connect(**pg_test_db)
    conn.autocommit = True
    assert conn.get_dsn_parameters()["dbname"] == TEST_DB  # guard before TRUNCATE
    with conn.cursor() as cur:
        cur.execute("TRUNCATE messages, sessions CASCADE")
    yield conn
    conn.close()


@pytest.fixture
def make_pool(pg_test_db):
    """Factory for real ThreadedConnectionPools on the test DB (closed afterwards)."""
    from medrag.memory.db import get_postgres_pool

    pools = []

    def _make(maxconn=3):
        pool = get_postgres_pool(
            pg_test_db["host"],
            pg_test_db["port"],
            pg_test_db["dbname"],
            pg_test_db["user"],
            pg_test_db["password"],
            minconn=1,
            maxconn=maxconn,
        )
        pools.append(pool)
        return pool

    yield _make
    for pool in pools:
        pool.closeall()


# --------------------------------------------------------------------------
# Qdrant
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def qdrant_client():
    url = os.environ.get("MEDRAG_TEST_QDRANT_URL") or settings.qdrant_url or "http://localhost:6333"
    client = QdrantClient(location=":memory:") if url == ":memory:" else QdrantClient(url=url)
    try:
        client.get_collections()
    except Exception as exc:
        pytest.fail(f"Cannot reach Qdrant at {url}. Is `docker compose up` running? ({exc})")
    return client


@pytest.fixture
def temp_collection(qdrant_client, monkeypatch):
    """A throwaway hybrid (dense + sparse) collection that the retrieval and upload
    modules are pointed at for the duration of one test."""
    name = f"medrag_test_{uuid.uuid4().hex[:10]}"
    assert name != "medrag_text"
    qdrant_client.create_collection(
        collection_name=name,
        vectors_config={
            DENSE_VECTOR_NAME: qmodels.VectorParams(size=EMBED_DIM, distance=qmodels.Distance.COSINE)
        },
        sparse_vectors_config={SPARSE_VECTOR_NAME: qmodels.SparseVectorParams()},
    )
    for module_name in ("medrag.retrieval.hybrid_search", "medrag.ingestion.user_upload"):
        monkeypatch.setattr(importlib.import_module(module_name), "TEXT_COLLECTION", name)
    yield SimpleNamespace(name=name, dim=EMBED_DIM)
    qdrant_client.delete_collection(name)
