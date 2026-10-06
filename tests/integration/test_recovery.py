"""Failure recovery and same-session ordering against isolated real stores."""
import importlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from medrag.memory import chat_memory as cm
from medrag.memory.db import session_operation, transaction

uu = importlib.import_module("medrag.ingestion.user_upload")
hs = importlib.import_module("medrag.retrieval.hybrid_search")
main = importlib.import_module("medrag.api.main")
pytestmark = pytest.mark.integration


def test_chat_citation_failure_rolls_back_the_complete_turn(pg_conn, make_pool, monkeypatch):
    monkeypatch.setattr(main.settings, "auth_required", False)
    sid = cm.create_session(pg_conn)
    pool = make_pool()
    monkeypatch.setattr(main.app.state, "pg_pool", pool, raising=False)
    for name in ("qdrant_client", "openai_client", "neo4j_driver"):
        monkeypatch.setattr(main.app.state, name, object(), raising=False)
    monkeypatch.setattr(main.app.state, "who_source_urls", {}, raising=False)
    def generate(query, session_id, conn, **kwargs):
        cm.add_message(conn, session_id, "user", query)
        mid = cm.add_message(conn, session_id, "assistant", "Answer [1]")
        return "Answer [1]", [], mid
    monkeypatch.setattr(main, "generate_answer_with_memory", generate)
    def broken_citations(*args):
        raise RuntimeError("citation failure")
    monkeypatch.setattr(main, "build_citations", broken_citations)
    response = TestClient(main.app, raise_server_exceptions=False).post("/chat", json={"session_id": sid, "message": "Q?"})
    assert response.status_code == 500
    assert cm.get_session_history(pg_conn, sid) == []
    assert cm.list_sessions(pg_conn)[0]["title"] is None
    monkeypatch.setattr(main, "build_citations", lambda *args: [])
    response = TestClient(main.app).post("/chat", json={"session_id": sid, "message": "Retry"})
    assert response.status_code == 200
    assert [m["content"] for m in cm.get_session_history(pg_conn, sid)] == ["Retry", "Answer [1]"]


def test_first_successful_question_names_chat_and_preserves_titles(pg_conn, make_pool, monkeypatch):
    monkeypatch.setattr(main.settings, "auth_required", False)
    monkeypatch.setattr(main.app.state, "pg_pool", make_pool(), raising=False)
    for name in ("qdrant_client", "openai_client", "neo4j_driver"):
        monkeypatch.setattr(main.app.state, name, object(), raising=False)
    monkeypatch.setattr(main.app.state, "who_source_urls", {}, raising=False)
    def generate(query, session_id, conn, **kwargs):
        cm.add_message(conn, session_id, "user", query)
        mid = cm.add_message(conn, session_id, "assistant", "Answer")
        return "Answer", [], mid
    monkeypatch.setattr(main, "generate_answer_with_memory", generate)
    client = TestClient(main.app)
    sid = cm.create_session(pg_conn)
    custom = cm.create_session(pg_conn, title="My Notes")
    for session_id, query in [(sid, "What is type 2 diabetes?"), (sid, "Explain asthma"), (custom, "Explain asthma")]:
        assert client.post("/chat", json={"session_id": session_id, "message": query}).status_code == 200
    titles = {s["session_id"]: s["title"] for s in cm.list_sessions(pg_conn)}
    assert titles[sid] == "Diabetes Type 2"
    assert titles[custom] == "My Notes"


def test_same_session_waits_and_sees_the_committed_previous_turn(pg_conn, make_pool):
    sid = cm.create_session(pg_conn)
    other_sid = cm.create_session(pg_conn)
    pool = make_pool(maxconn=3)
    entered = threading.Event()
    release = threading.Event()
    second_attempt = threading.Event()
    second_entered = threading.Event()
    def first():
        conn = pool.getconn()
        conn.autocommit = True
        try:
            with session_operation(conn, sid), transaction(conn):
                cm.add_message(conn, sid, "user", "First")
                entered.set()
                assert release.wait(5)
                cm.add_message(conn, sid, "assistant", "Answer")
        finally:
            pool.putconn(conn)
    def second(session_id):
        conn = pool.getconn()
        conn.autocommit = True
        try:
            second_attempt.set()
            with session_operation(conn, session_id):
                if session_id == sid:
                    second_entered.set()
                return [m["content"] for m in cm.get_session_history(conn, session_id)]
        finally:
            pool.putconn(conn)
    with ThreadPoolExecutor(max_workers=3) as executor:
        first_future = executor.submit(first)
        assert entered.wait(5)
        second_future = executor.submit(second, sid)
        assert second_attempt.wait(5)
        try:
            assert executor.submit(second, other_sid).result(timeout=3) == []
            assert not second_entered.wait(0.15)
        finally:
            release.set()
        first_future.result(timeout=5)
        assert second_future.result(timeout=5) == ["First", "Answer"]


@pytest.fixture
def uploader(pg_conn, qdrant_client, temp_collection, monkeypatch):
    sid = cm.create_session(pg_conn)
    monkeypatch.setattr(uu, "extract_text_from_pdf", lambda _: "One. Two.")
    monkeypatch.setattr(uu, "sentence_based_chunk", lambda *a, **k: ["One.", "Two."])
    monkeypatch.setattr(uu, "build_batches", lambda chunks: [[c] for c in chunks])
    sparse = SimpleNamespace(indices=np.array([1, 2]), values=np.array([1.0, 1.0]))
    monkeypatch.setattr(uu, "get_sparse_model", lambda: SimpleNamespace(embed=lambda texts: [sparse for _ in texts]))
    embed = Mock(side_effect=lambda client, texts: [[1.0] + [0.0] * (temp_collection.dim - 1) for _ in texts])
    monkeypatch.setattr(uu, "embed_batch_with_retry", embed)
    def upload():
        with session_operation(pg_conn, sid):
            return uu.index_document(pg_conn, sid, b"same PDF bytes", "labs.pdf", qdrant_client, object())
    return SimpleNamespace(upload=upload, sid=sid, embed=embed, client=qdrant_client, collection=temp_collection.name)


def test_upload_failure_hides_staging_and_cleans_up(uploader, pg_conn, monkeypatch):
    real_upsert = uploader.client.upsert
    calls = []
    def fail_second(**kwargs):
        if calls:
            assert uploader.client.count(uploader.collection, count_filter=hs.build_user_filter(uploader.sid), exact=True).count == 0
            raise ConnectionError("indexing interrupted")
        calls.append(1)
        return real_upsert(**kwargs)
    monkeypatch.setattr(uploader.client, "upsert", fail_second)
    with pytest.raises(ConnectionError):
        uploader.upload()
    assert uploader.client.count(uploader.collection, exact=True).count == 0
    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uploaded_documents WHERE session_id = %s", (uploader.sid,))
        assert cur.fetchone()[0] == 0
    monkeypatch.setattr(uploader.client, "upsert", real_upsert)
    first = uploader.upload()
    calls_before_retry = uploader.embed.call_count
    assert uploader.upload() == first
    assert uploader.embed.call_count == calls_before_retry
    assert uploader.client.count(uploader.collection, exact=True).count == 2


def test_publication_failure_is_repaired_without_reembedding(uploader, monkeypatch):
    publish = uu.publish_upload
    monkeypatch.setattr(uu, "publish_upload", Mock(side_effect=ConnectionError("publish interrupted")))
    with pytest.raises(ConnectionError):
        uploader.upload()
    assert uploader.client.count(uploader.collection, count_filter=hs.build_user_filter(uploader.sid), exact=True).count == 0
    calls_before_retry = uploader.embed.call_count
    monkeypatch.setattr(uu, "publish_upload", publish)
    result = uploader.upload()
    assert result["chunk_count"] == 2
    assert uploader.embed.call_count == calls_before_retry
    assert uploader.client.count(uploader.collection, count_filter=hs.build_user_filter(uploader.sid), exact=True).count == 2
