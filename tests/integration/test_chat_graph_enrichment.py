"""Integration tests (real Postgres) for two things coverage showed were untested:

1. db.py helpers: ensure_schema_via_pool (what the API calls at startup) and the
   direct-connection helper kept for scripts.
2. The knowledge-graph branch of generate_answer_with_memory, including the Phase 16
   design point that drug detection runs on the REWRITTEN query. A follow-up such as
   "What are its contraindications?" names no drug until it has been reformulated.
"""

import importlib
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.integration

cm = importlib.import_module("medrag.memory.chat_memory")
db_mod = importlib.import_module("medrag.memory.db")


# --------------------------------------------------------------------------
# db.py helpers
# --------------------------------------------------------------------------
def test_ensure_schema_via_pool_is_idempotent_and_returns_its_connection(make_pool, pg_conn):
    pool = make_pool(maxconn=1)

    db_mod.ensure_schema_via_pool(pool)
    db_mod.ensure_schema_via_pool(pool)  # would raise PoolError if the first call leaked its connection

    with pg_conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.sessions') IS NOT NULL, to_regclass('public.messages') IS NOT NULL")
        assert cur.fetchone() == (True, True)


def test_direct_connection_helper_returns_an_autocommit_connection(pg_test_db):
    conn = db_mod.get_postgres_connection(
        pg_test_db["host"], pg_test_db["port"], pg_test_db["dbname"],
        pg_test_db["user"], pg_test_db["password"],
    )
    try:
        assert conn.autocommit is True
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Graph enrichment inside generate_answer_with_memory
# --------------------------------------------------------------------------
class ScriptedOpenAI:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages):
        self.calls.append(messages)
        content = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def graph(monkeypatch):
    """Fake retrieval and the knowledge graph; spy on drug detection."""
    rec = SimpleNamespace(find_queries=[], curated_calls=[])
    results = [
        {
            "payload": {
                "chunk_id": "c1", "source": "pubmed", "source_id": "111",
                "raw_text": "Metformin is a biguanide.", "metadata": {"title": "T"},
            }
        }
    ]
    monkeypatch.setattr(cm, "search_with_reranking", lambda *a, **k: results)
    monkeypatch.setattr(cm, "get_all_known_drug_names", lambda driver: ["metformin"])

    real_find = cm.find_mentioned_drug

    def spy_find(query, names):
        rec.find_queries.append(query)
        return real_find(query, names)

    def fake_curated(driver, drug):
        rec.curated_calls.append((driver, drug))
        return [{"drug": "Metformin", "relationship": "CONTRAINDICATED_IN", "disease": "renal impairment"}]

    monkeypatch.setattr(cm, "find_mentioned_drug", spy_find)
    monkeypatch.setattr(cm, "get_graph_facts_for_drug_curated", fake_curated)
    return rec


def system_prompt(openai_client, call_index=-1):
    return openai_client.calls[call_index][0]["content"]


def test_drug_detection_runs_on_the_rewritten_query_not_the_follow_up(pg_conn, graph):
    sid = cm.create_session(pg_conn)
    cm.generate_answer_with_memory(  # turn 1 builds the history
        "What is metformin?", sid, pg_conn, qdrant_client=object(),
        openai_client=ScriptedOpenAI("A biguanide."), user_id=sid,
    )
    graph.find_queries.clear()
    driver = object()
    openai_client = ScriptedOpenAI("What are metformin's contraindications?", "Renal impairment [1].")

    cm.generate_answer_with_memory(
        "What are its contraindications?", sid, pg_conn, qdrant_client=object(),
        openai_client=openai_client, neo4j_driver=driver, user_id=sid,
    )

    assert graph.find_queries == ["What are metformin's contraindications?"]  # the rewrite
    assert graph.curated_calls == [(driver, "metformin")]
    prompt = system_prompt(openai_client)  # generation call is the last one
    assert "Candidate relationships" in prompt
    assert "- Metformin CONTRAINDICATED_IN renal impairment" in prompt


def test_the_original_follow_up_alone_would_have_missed_the_drug():
    """Why the rewrite matters: with the follow-up text, detection finds nothing."""
    assert cm.find_mentioned_drug("What are its contraindications?", ["metformin"]) is None


def test_follow_up_language_uses_original_query_even_after_foreign_history(pg_conn, graph):
    sid = cm.create_session(pg_conn)
    cm.add_message(pg_conn, sid, "user", "Что такое гипертония?")
    cm.add_message(pg_conn, sid, "assistant", "Повышенное давление.")
    client = ScriptedOpenAI("Что значит антигипертензивное средство?", "An antihypertensive lowers blood pressure [1].")
    cm.generate_answer_with_memory("antihypertensive what its means?", sid, pg_conn,
                                  qdrant_client=object(), openai_client=client, user_id=sid)
    assert "Respond exclusively in English" in system_prompt(client)
    assert client.calls[-1][-1]["content"] == "antihypertensive what its means?"


def test_no_neo4j_driver_means_no_graph_section_and_no_graph_calls(pg_conn, graph):
    sid = cm.create_session(pg_conn)
    openai_client = ScriptedOpenAI("Answer.")

    cm.generate_answer_with_memory(
        "What is metformin?", sid, pg_conn, qdrant_client=object(),
        openai_client=openai_client, neo4j_driver=None,
    )

    assert "Candidate relationships" not in system_prompt(openai_client)
    assert graph.find_queries == [] and graph.curated_calls == []


def test_driver_present_but_no_known_drug_mentioned_adds_nothing(pg_conn, graph):
    sid = cm.create_session(pg_conn)
    openai_client = ScriptedOpenAI("Answer.")

    cm.generate_answer_with_memory(
        "What is hypertension?", sid, pg_conn, qdrant_client=object(),
        openai_client=openai_client, neo4j_driver=object(),
    )

    assert graph.find_queries == ["What is hypertension?"]  # looked, found nothing
    assert graph.curated_calls == []
    assert "Candidate relationships" not in system_prompt(openai_client)
