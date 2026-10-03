"""API endpoint tests (Phase 18/19/20), with all backends faked.

What is real here: routing, request validation, status codes, error mapping,
and the wiring between each route and the pipeline functions it calls.
What is faked: Postgres, Qdrant, Neo4j, OpenAI, and the pipeline internals.
"""

import importlib
import uuid

import psycopg2.pool
import pytest

main = importlib.import_module("medrag.api.main")
uu = importlib.import_module("medrag.ingestion.user_upload")

PDF_FILE = {"file": ("labs.pdf", b"%PDF-1.4 fake", "application/pdf")}


def assert_no_connection_leaked(state):
    assert state.pg_pool.returned == state.pg_pool.checked_out


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------
def test_create_session_returns_the_new_id_and_creates_it_without_a_user_id(client, db, sid):
    resp = client.post("/sessions", json={"title": "Diabetes chat"})

    assert resp.status_code == 200
    assert resp.json() == {"session_id": sid}
    # session_id itself is the isolation key (see main.py docstring)
    assert db.created == [{"title": "Diabetes chat", "user_id": None}]


def test_get_unknown_session_is_404(client, db, sid):
    db.exists = False
    resp = client.get(f"/sessions/{sid}")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_get_session_returns_its_messages_in_order(client, db, sid, message_row):
    db.history = [message_row("user", "hi"), message_row("assistant", "hello")]

    body = client.get(f"/sessions/{sid}").json()

    assert body["session_id"] == sid
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("user", "hi"),
        ("assistant", "hello"),
    ]


def test_list_sessions(client, db, sid):
    db.sessions = [{"session_id": sid, "title": "t", "created_at": "2026-01-01", "updated_at": "2026-01-02"}]
    body = client.get("/sessions").json()
    assert [s["session_id"] for s in body["sessions"]] == [sid]


# --------------------------------------------------------------------------
# /chat
# --------------------------------------------------------------------------
def test_chat_returns_the_answer_with_resolved_citations(client, pipeline, sid):
    resp = client.post("/chat", json={"session_id": sid, "message": "First-line for T2D?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Metformin is first-line [1]."
    (citation,) = body["citations"]
    assert citation["marker"] == 1
    assert citation["chunk_id"] == "c1"
    assert citation["title"] == "Metformin trial"
    assert citation["url"] == "https://pubmed.ncbi.nlm.nih.gov/111/"


def test_chat_persists_citations_on_the_stored_assistant_message(client, pipeline, sid):
    body = client.post("/chat", json={"session_id": sid, "message": "q"}).json()

    ((_, message_id, citations),) = pipeline.citation_updates
    assert message_id == "msg-42"
    assert citations == body["citations"]


def test_chat_answer_without_markers_stores_an_empty_citation_list(client, pipeline, sid):
    pipeline.answer = "The context does not cover this."
    body = client.post("/chat", json={"session_id": sid, "message": "q"}).json()
    assert body["citations"] == []
    assert pipeline.citation_updates[0][2] == []


def test_chat_scopes_retrieval_to_the_session_as_the_isolation_key(client, pipeline, sid):
    """Isolation wiring: uploads are visible only inside the session they were
    made in, because /chat passes session_id as user_id to retrieval."""
    client.post("/chat", json={"session_id": sid, "message": "q"})
    (call,) = pipeline.calls
    assert call.session_id == sid
    assert call.user_id == sid


def test_chat_hands_the_shared_clients_from_app_state_to_the_pipeline(client, pipeline, state, sid):
    client.post("/chat", json={"session_id": sid, "message": "q"})
    (call,) = pipeline.calls
    assert call.qdrant_client is state.qdrant_client
    assert call.openai_client is state.openai_client
    assert call.neo4j_driver is state.neo4j_driver


def test_chat_uses_one_connection_for_pipeline_and_citation_update(client, pipeline, state, sid):
    client.post("/chat", json={"session_id": sid, "message": "q"})

    (call,) = pipeline.calls
    assert call.conn is pipeline.citation_updates[0][0]
    assert len(state.pg_pool.checked_out) == 1
    assert_no_connection_leaked(state)


def test_chat_unknown_session_is_404_and_the_pipeline_never_runs(client, pipeline, db, state, sid):
    db.exists = False
    resp = client.post("/chat", json={"session_id": sid, "message": "q"})
    assert resp.status_code == 404
    assert pipeline.calls == []
    assert_no_connection_leaked(state)


def test_chat_rejects_a_request_without_a_message(client, pipeline, sid):
    assert client.post("/chat", json={"session_id": sid}).status_code == 422


# --------------------------------------------------------------------------
# /sessions/{id}/documents
# --------------------------------------------------------------------------
def test_upload_success_tags_chunks_with_the_session_as_isolation_key(client, upload_pipeline, state, sid):
    resp = client.post(f"/sessions/{sid}/documents", files=PDF_FILE)

    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "labs.pdf"
    assert body["chunk_count"] == 2
    assert str(uuid.UUID(body["document_id"])) == body["document_id"]

    (call,) = upload_pipeline.chunk_calls
    assert call["text"] == "Extracted body text."
    assert call["user_id"] == sid  # the isolation key
    assert call["session_id"] == sid
    assert call["filename"] == "labs.pdf"
    assert call["document_id"] == body["document_id"]


def test_upload_embeds_through_the_shared_clients(client, upload_pipeline, state, sid):
    client.post(f"/sessions/{sid}/documents", files=PDF_FILE)
    ((chunks, qdrant, openai_client),) = upload_pipeline.embed_calls
    assert chunks == ["chunkA", "chunkB"]
    assert qdrant is state.qdrant_client
    assert openai_client is state.openai_client


def test_upload_to_unknown_session_is_404_before_any_other_check(client, upload_pipeline, db, sid):
    db.exists = False
    wrong_type = {"file": ("notes.txt", b"hello", "text/plain")}
    resp = client.post(f"/sessions/{sid}/documents", files=wrong_type)
    assert resp.status_code == 404
    assert upload_pipeline.chunk_calls == []


def test_upload_of_a_non_pdf_content_type_is_400(client, upload_pipeline, sid):
    resp = client.post(
        f"/sessions/{sid}/documents", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert resp.status_code == 400
    assert "Only PDF" in resp.json()["detail"]
    assert upload_pipeline.chunk_calls == []


def test_upload_over_the_size_limit_is_413(client, upload_pipeline, monkeypatch, sid):
    monkeypatch.setattr(uu, "MAX_FILE_SIZE_BYTES", 10)  # real validator, tiny limit
    resp = client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("big.pdf", b"x" * 11, "application/pdf")},
    )
    assert resp.status_code == 413
    assert "exceeds" in resp.json()["detail"]
    assert upload_pipeline.chunk_calls == []


def test_upload_of_an_unreadable_pdf_is_422(client, db, sid):
    # No upload_pipeline here: the REAL extractor runs and rejects the garbage.
    resp = client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("broken.pdf", b"this is not a pdf", "application/pdf")},
    )
    assert resp.status_code == 422
    assert "Could not open or read PDF" in resp.json()["detail"]


# --------------------------------------------------------------------------
# /health
# --------------------------------------------------------------------------
def boom(*args, **kwargs):
    raise RuntimeError("down")


def test_health_is_ok_when_every_dependency_is_up(client, state):
    assert client.get("/health").json() == {
        "status": "ok",
        "dependencies": {"qdrant": "ok", "neo4j": "ok", "postgres": "ok"},
    }


@pytest.mark.parametrize("broken", ["qdrant", "neo4j", "postgres"])
def test_health_is_degraded_and_names_the_failing_dependency(client, state, broken):
    if broken == "qdrant":
        state.qdrant_client.get_collections = boom
    elif broken == "neo4j":
        state.neo4j_driver.verify_connectivity = boom
    else:
        state.pg_pool.fail_with = RuntimeError("down")

    body = client.get("/health").json()

    assert body["status"] == "degraded"
    assert body["dependencies"][broken].startswith("error:")
    healthy = {"qdrant", "neo4j", "postgres"} - {broken}
    assert all(body["dependencies"][name] == "ok" for name in healthy)


# --------------------------------------------------------------------------
# get_conn: per-request connection hygiene (Phase 20 Part 2)
# --------------------------------------------------------------------------
def test_get_conn_enables_autocommit_and_returns_the_connection_afterwards(state):
    with main.get_conn(main.app) as conn:
        assert conn.autocommit is True
        assert state.pg_pool.returned == []
    assert state.pg_pool.returned == [conn]


def test_get_conn_returns_the_connection_even_when_the_request_raises(state):
    with pytest.raises(RuntimeError):
        with main.get_conn(main.app) as conn:
            raise RuntimeError("boom")
    assert state.pg_pool.returned == [conn]


def test_each_request_checks_out_its_own_connection(client, db, state):
    client.get("/sessions")
    client.get("/sessions")
    assert len(state.pg_pool.checked_out) == 2
    assert state.pg_pool.checked_out[0] is not state.pg_pool.checked_out[1]
    assert_no_connection_leaked(state)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT: psycopg2's ThreadedConnectionPool raises PoolError immediately when "
        "all connections are checked out (it does not wait), and /chat holds one for "
        "its whole pipeline. The 11th concurrent request, even /health, therefore gets "
        "an unhandled 500. Fix: map PoolError to 503 (or gate checkouts with a "
        "semaphore), then drop this marker."
    ),
)
def test_pool_exhaustion_is_a_retryable_503_not_a_500(client_no_raise, state):
    state.pg_pool.fail_with = psycopg2.pool.PoolError("connection pool exhausted")
    assert client_no_raise.get("/sessions").status_code == 503
