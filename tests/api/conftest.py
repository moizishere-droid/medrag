"""Shared fixtures for the API tests.

The real FastAPI app is used, with every backend (Postgres pool, Qdrant, Neo4j,
OpenAI) replaced by a fake. The lifespan is deliberately never run: it connects
to real services, so the `state` fixture fills app.state by hand instead and
TestClient is used WITHOUT a `with` block.
"""

import importlib
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

main = importlib.import_module("medrag.api.main")

SESSION_ID = "11111111-1111-1111-1111-111111111111"


# --------------------------------------------------------------------------
# Fake Postgres pool
# --------------------------------------------------------------------------
class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return None


class FakeConn:
    def __init__(self):
        self.autocommit = False
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def cursor(self, *args, **kwargs):
        return FakeCursor()


class FakePool:
    """Records every checkout and return so tests can assert nothing leaks."""

    def __init__(self):
        self.checked_out = []
        self.returned = []
        self.fail_with = None  # set to an exception to simulate a broken pool

    def getconn(self):
        if self.fail_with is not None:
            raise self.fail_with
        conn = FakeConn()
        self.checked_out.append(conn)
        return conn

    def putconn(self, conn):
        self.returned.append(conn)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def sid():
    return SESSION_ID


@pytest.fixture
def message_row():
    """Factory for a row shaped like `SELECT * FROM messages`."""

    def _make(role, content, citations=None):
        return {
            "message_id": "22222222-2222-2222-2222-222222222222",
            "session_id": SESSION_ID,
            "role": role,
            "content": content,
            "citations": citations,
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }

    return _make


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setattr(main.settings, "auth_required", False)
    s = main.app.state
    s.pg_pool = FakePool()
    s.qdrant_client = SimpleNamespace(get_collections=lambda: [])
    s.neo4j_driver = SimpleNamespace(verify_connectivity=lambda: None)
    s.openai_client = object()
    s.who_source_urls = {}
    return s


@pytest.fixture
def client(state):
    # No `with`: entering the context would run the lifespan (real services).
    return TestClient(main.app)


@pytest.fixture
def client_no_raise(state):
    """Like `client`, but unhandled server errors come back as HTTP 500."""
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def db(monkeypatch, state, sid):
    """Fake the chat_memory functions main.py imports; tests mutate the record."""
    rec = SimpleNamespace(exists=True, created=[], history=[], sessions=[], new_session_id=sid)

    monkeypatch.setattr(main, "session_exists", lambda conn, session_id: rec.exists)

    def create(conn, title=None, user_id=None):
        rec.created.append({"title": title, "user_id": user_id})
        return rec.new_session_id

    monkeypatch.setattr(main, "create_session", create)
    monkeypatch.setattr(main, "get_session_history", lambda conn, session_id: rec.history)
    monkeypatch.setattr(main, "list_sessions", lambda conn: rec.sessions)
    return rec


@pytest.fixture
def pipeline(monkeypatch, db):
    """Fake generate_answer_with_memory and update_message_citations."""
    rec = SimpleNamespace(
        calls=[],
        citation_updates=[],
        delay=0.0,
        answer="Metformin is first-line [1].",
        results=[
            {
                "payload": {
                    "chunk_id": "c1",
                    "source": "pubmed",
                    "source_id": "111",
                    "raw_text": "Metformin text.",
                    "metadata": {"title": "Metformin trial"},
                }
            }
        ],
        message_id="msg-42",
    )

    def fake_generate(message, session_id, conn, **kwargs):
        rec.calls.append(SimpleNamespace(message=message, session_id=session_id, conn=conn, **kwargs))
        time.sleep(rec.delay)  # runs on a worker thread, so this must not block the loop
        return rec.answer, rec.results, rec.message_id

    def fake_update(conn, message_id, citations):
        rec.citation_updates.append((conn, message_id, citations))

    monkeypatch.setattr(main, "generate_answer_with_memory", fake_generate)
    monkeypatch.setattr(main, "update_message_citations", fake_update)
    return rec


@pytest.fixture
def upload_pipeline(monkeypatch, db):
    """Fake text extraction, chunking and embedding for the upload route."""
    rec = SimpleNamespace(chunk_calls=[], embed_calls=[], extract_delay=0.0)

    def fake_extract(file_bytes):
        time.sleep(rec.extract_delay)
        return "Extracted body text."

    def fake_chunk(**kwargs):
        rec.chunk_calls.append(kwargs)
        return ["chunkA", "chunkB"]

    def fake_embed(chunks, qdrant_client, openai_client):
        rec.embed_calls.append((chunks, qdrant_client, openai_client))
        return len(chunks)

    monkeypatch.setattr(main, "extract_text_from_pdf", fake_extract)
    monkeypatch.setattr(main, "chunk_user_upload", fake_chunk)
    monkeypatch.setattr(main, "embed_and_upsert_upload_chunks", fake_embed)
    def fake_index(conn, session_id, file_bytes, filename, qdrant_client, openai_client):
        import uuid
        text = main.extract_text_from_pdf(file_bytes)
        chunks = fake_chunk(text=text, user_id=session_id, session_id=session_id,
                            document_id=str(uuid.uuid4()), filename=filename)
        count = fake_embed(chunks, qdrant_client, openai_client)
        return {"document_id": rec.chunk_calls[-1]["document_id"], "filename": filename, "chunk_count": count}
    monkeypatch.setattr(main.user_upload, "index_document", fake_index)
    return rec
