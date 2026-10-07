"""Integration tests for chat memory against a REAL Postgres (the test database).

Covers the SQL in chat_memory.py / db.py (ordering, windows, constraints, JSONB),
the connection pool's thread behaviour (Phase 20 Part 2), and the full
history-aware pipeline with OpenAI and retrieval faked.
"""

import importlib
import threading
import time
import uuid
from types import SimpleNamespace

import psycopg2.errors
import psycopg2.pool
import pytest

pytestmark = pytest.mark.integration

cm = importlib.import_module("medrag.memory.chat_memory")
db_mod = importlib.import_module("medrag.memory.db")
main = importlib.import_module("medrag.api.main")


def add(conn, session_id, role, content, **kwargs):
    """add_message with a pause so created_at values are strictly increasing."""
    message_id = cm.add_message(conn, session_id, role, content, **kwargs)
    time.sleep(0.003)
    return message_id


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
def test_schema_creation_is_idempotent_and_has_the_expected_columns(pg_conn):
    db_mod.ensure_schema(pg_conn)
    db_mod.ensure_schema(pg_conn)  # second run must not fail

    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name IN ('sessions', 'messages')"
        )
        columns = {(t, c) for t, c in cur.fetchall()}

    assert {("sessions", c) for c in ("session_id", "user_id", "title", "created_at", "updated_at")} <= columns
    assert {("messages", c) for c in ("message_id", "session_id", "role", "content", "citations", "created_at")} <= columns


def test_role_constraint_rejects_anything_but_user_or_assistant(pg_conn):
    sid = cm.create_session(pg_conn)
    with pytest.raises(psycopg2.errors.CheckViolation):
        cm.add_message(pg_conn, sid, "system", "x")


def test_a_message_for_a_nonexistent_session_violates_the_foreign_key(pg_conn):
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        cm.add_message(pg_conn, str(uuid.uuid4()), "user", "x")


def test_deleting_a_session_cascades_to_its_messages(pg_conn):
    sid = cm.create_session(pg_conn)
    add(pg_conn, sid, "user", "hi")
    with pg_conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
        cur.execute("SELECT count(*) FROM messages WHERE session_id = %s", (sid,))
        assert cur.fetchone()[0] == 0


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------
def test_create_session_returns_a_uuid_string_and_it_exists(pg_conn):
    sid = cm.create_session(pg_conn, title="t")
    assert str(uuid.UUID(sid)) == sid
    assert cm.session_exists(pg_conn, sid) is True


def test_unknown_but_well_formed_session_does_not_exist(pg_conn):
    assert cm.session_exists(pg_conn, str(uuid.uuid4())) is False


def test_malformed_session_id_is_reported_as_not_existing(pg_conn):
    assert cm.session_exists(pg_conn, "not-a-uuid") is False


def test_session_user_id_round_trip(pg_conn):
    plain = cm.create_session(pg_conn)
    owned = cm.create_session(pg_conn, user_id="user-7")
    assert cm.get_session_user_id(pg_conn, plain) is None
    assert cm.get_session_user_id(pg_conn, owned) == "user-7"
    assert cm.get_session_user_id(pg_conn, str(uuid.uuid4())) is None


def test_list_sessions_orders_by_most_recent_activity_and_add_message_bumps_it(pg_conn):
    first = cm.create_session(pg_conn, title="first")
    time.sleep(0.01)
    second = cm.create_session(pg_conn, title="second")
    assert [s["session_id"] for s in cm.list_sessions(pg_conn)] == [second, first]

    time.sleep(0.01)
    add(pg_conn, first, "user", "bump")  # touching `first` makes it the most recent

    listed = cm.list_sessions(pg_conn)
    assert [s["session_id"] for s in listed] == [first, second]
    assert set(listed[0]) == {"session_id", "title", "created_at", "updated_at"}


# --------------------------------------------------------------------------
# Messages and history
# --------------------------------------------------------------------------
def test_history_is_chronological_and_isolated_per_session(pg_conn):
    a = cm.create_session(pg_conn)
    b = cm.create_session(pg_conn)
    add(pg_conn, a, "user", "a1")
    add(pg_conn, b, "user", "b1")
    add(pg_conn, a, "assistant", "a2")

    assert [m["content"] for m in cm.get_session_history(pg_conn, a)] == ["a1", "a2"]
    assert [m["content"] for m in cm.get_session_history(pg_conn, b)] == ["b1"]


def test_history_limit_returns_the_most_recent_n_in_chronological_order(pg_conn):
    sid = cm.create_session(pg_conn)
    for i in range(6):
        add(pg_conn, sid, "user" if i % 2 == 0 else "assistant", f"m{i}")

    assert [m["content"] for m in cm.get_session_history(pg_conn, sid, limit=3)] == ["m3", "m4", "m5"]
    assert len(cm.get_session_history(pg_conn, sid)) == 6  # limit=None returns everything


def test_message_history_for_the_model_has_only_role_and_content_and_is_bounded(pg_conn):
    sid = cm.create_session(pg_conn)
    for i in range(6):
        add(pg_conn, sid, "user" if i % 2 == 0 else "assistant", f"m{i}", citations=[{"marker": 1}])

    history = cm.build_message_history(pg_conn, sid, bounded_turns=2)  # 2 turns = 4 messages

    assert [m["content"] for m in history] == ["m2", "m3", "m4", "m5"]
    assert all(set(m) == {"role", "content"} for m in history)  # citations stripped


def test_citations_round_trip_as_jsonb_and_can_be_replaced_later(pg_conn):
    sid = cm.create_session(pg_conn)
    citations = [{"marker": 1, "chunk_id": "c1", "url": None, "linked_images": []}]
    message_id = add(pg_conn, sid, "assistant", "answer [1]", citations=citations)

    assert cm.get_session_history(pg_conn, sid)[0]["citations"] == citations

    replacement = [{"marker": 2, "chunk_id": "c2"}]
    cm.update_message_citations(pg_conn, message_id, replacement)
    assert cm.get_session_history(pg_conn, sid)[0]["citations"] == replacement


def test_empty_citation_list_is_stored_as_null(pg_conn):
    """Characterization: [] and None both become SQL NULL, so a message that had
    'no citations' reads back as None, not []."""
    sid = cm.create_session(pg_conn)
    message_id = add(pg_conn, sid, "assistant", "no sources", citations=[])
    assert cm.get_session_history(pg_conn, sid)[0]["citations"] is None

    cm.update_message_citations(pg_conn, message_id, [{"marker": 1}])
    cm.update_message_citations(pg_conn, message_id, [])
    assert cm.get_session_history(pg_conn, sid)[0]["citations"] is None


# --------------------------------------------------------------------------
# Connection pool (Phase 20 Part 2)
# --------------------------------------------------------------------------
def test_exhausted_pool_raises_immediately_instead_of_waiting(make_pool):
    """Characterization of psycopg2's behaviour, the root of the 500-on-exhaustion
    defect pinned in tests/api/test_endpoints.py."""
    pool = make_pool(maxconn=2)
    held = [pool.getconn(), pool.getconn()]
    with pytest.raises(psycopg2.pool.PoolError):
        pool.getconn()
    for conn in held:
        pool.putconn(conn)
    pool.putconn(pool.getconn())  # capacity is back after the connections are returned


def test_concurrent_threads_get_separate_connections(make_pool):
    """The point of the pool: threads that hold connections at the same moment
    must be talking over different backend processes, never one shared one."""
    pool = make_pool(maxconn=3)
    barrier = threading.Barrier(3)
    pids, errors = [], []

    def worker():
        try:
            conn = pool.getconn()
            try:
                barrier.wait(timeout=10)  # all three hold a connection simultaneously
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_backend_pid()")
                    pids.append(cur.fetchone()[0])
                conn.rollback()
            finally:
                pool.putconn(conn)
        except Exception as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert errors == []
    assert len(set(pids)) == 3


def test_get_conn_returns_the_connection_to_a_real_pool_even_if_the_request_raises(make_pool):
    pool = make_pool(maxconn=1)
    app = SimpleNamespace(state=SimpleNamespace(pg_pool=pool))

    with pytest.raises(RuntimeError):
        with main.get_conn(app):
            raise RuntimeError("request failed")

    with main.get_conn(app) as conn:  # would raise PoolError if the first one had leaked
        assert conn.autocommit is True


# --------------------------------------------------------------------------
# generate_answer_with_memory (real Postgres; OpenAI and retrieval faked)
# --------------------------------------------------------------------------
class ScriptedOpenAI:
    """Returns the queued replies in order and records every messages list."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages):
        self.calls.append(messages)
        content = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def retrieval(monkeypatch):
    rec = SimpleNamespace(
        calls=[],
        results=[
            {
                "payload": {
                    "chunk_id": "c1",
                    "source": "pubmed",
                    "source_id": "111",
                    "raw_text": "Metformin is a biguanide.",
                    "metadata": {"title": "T"},
                }
            }
        ],
    )

    def fake(client, query, candidate_pool_size, top_n, user_id=None):
        rec.calls.append({"query": query, "user_id": user_id, "pool": candidate_pool_size, "top_n": top_n})
        return rec.results

    monkeypatch.setattr(cm, "search_with_reranking", fake)
    return rec


def test_first_turn_skips_reformulation_and_persists_both_messages(pg_conn, retrieval):
    sid = cm.create_session(pg_conn)
    openai_client = ScriptedOpenAI("Metformin is a biguanide [1].")

    answer, results, assistant_id = cm.generate_answer_with_memory(
        "What is metformin?", sid, pg_conn, qdrant_client=object(), openai_client=openai_client, user_id=sid
    )

    assert answer == "Metformin is a biguanide [1]."
    assert results == retrieval.results
    assert len(openai_client.calls) == 1  # no history, so no reformulation call
    assert retrieval.calls == [{"query": "What is metformin?", "user_id": sid, "pool": 20, "top_n": 5}]

    system, user = openai_client.calls[0]
    assert system["role"] == "system" and "Metformin is a biguanide." in system["content"]
    assert user == {"role": "user", "content": "What is metformin?"}

    history = cm.get_session_history(pg_conn, sid)
    assert [(m["role"], m["content"]) for m in history] == [
        ("user", "What is metformin?"),
        ("assistant", "Metformin is a biguanide [1]."),
    ]
    assert str(history[1]["message_id"]) == assistant_id  # id returned for citation update


def test_follow_up_retrieves_with_the_rewritten_query_but_answers_the_original(pg_conn, retrieval):
    sid = cm.create_session(pg_conn)
    cm.generate_answer_with_memory(
        "What is metformin?", sid, pg_conn, qdrant_client=object(),
        openai_client=ScriptedOpenAI("It is a biguanide."), user_id=sid,
    )
    retrieval.calls.clear()

    openai_client = ScriptedOpenAI("What are metformin's contraindications?", "Renal impairment.")
    answer, _, _ = cm.generate_answer_with_memory(
        "What are its contraindications?", sid, pg_conn, qdrant_client=object(),
        openai_client=openai_client, user_id=sid,
    )

    reformulation, generation = openai_client.calls
    assert "Standalone question:" in reformulation[0]["content"]
    assert "user: What is metformin?" in reformulation[0]["content"]  # history was supplied

    assert retrieval.calls[0]["query"] == "What are metformin's contraindications?"  # rewritten

    assert generation[0]["role"] == "system"
    assert [m["content"] for m in generation[1:-1]] == ["What is metformin?", "It is a biguanide."]
    assert generation[-1] == {"role": "user", "content": "What are its contraindications?"}  # original
    assert answer == "Renal impairment."
    assert len(cm.get_session_history(pg_conn, sid)) == 4


def test_explicit_topic_question_skips_rewrite_but_keeps_history(pg_conn, retrieval):
    sid = cm.create_session(pg_conn)
    cm.add_message(pg_conn, sid, "user", "Earlier question")
    cm.add_message(pg_conn, sid, "assistant", "Earlier answer")
    client = ScriptedOpenAI("Diabetes answer [1].")
    cm.generate_answer_with_memory("What is diabetes?", sid, pg_conn,
                                  qdrant_client=object(), openai_client=client, user_id=sid)
    assert len(client.calls) == 1
    assert client.calls[0][1]["content"] == "Earlier question"
    assert retrieval.calls[0]["query"] == "What is diabetes?"


def test_user_id_none_is_forwarded_unchanged(pg_conn, retrieval):
    sid = cm.create_session(pg_conn)
    cm.generate_answer_with_memory(
        "q", sid, pg_conn, qdrant_client=object(), openai_client=ScriptedOpenAI("a"),
    )
    assert retrieval.calls[0]["user_id"] is None
