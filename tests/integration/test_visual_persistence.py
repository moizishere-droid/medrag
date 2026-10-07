"""Visual evidence survives a real PostgreSQL chat history round trip."""
import importlib

import pytest
from fastapi.testclient import TestClient
from medrag.memory.chat_memory import create_session, add_message

pytestmark = pytest.mark.integration
main = importlib.import_module("medrag.api.main")


def test_source_table_survives_real_database_reload(pg_conn, make_pool, monkeypatch):
    monkeypatch.setattr(main.settings, "auth_required", False)
    monkeypatch.setattr(main.app.state, "pg_pool", make_pool(), raising=False)
    for name in ("qdrant_client", "openai_client", "neo4j_driver"):
        monkeypatch.setattr(main.app.state, name, object(), raising=False)
    monkeypatch.setattr(main.app.state, "who_source_urls", {}, raising=False)
    rows = [["Measure", "Finding"], ["A", "B"]]
    def generate(query, sid, conn, **kwargs):
        add_message(conn, sid, "user", query)
        mid = add_message(conn, sid, "assistant", "Evidence [1]")
        results = [{"payload": {"source": "who", "source_id": "diabetes", "chunk_id": "table",
                                 "chunk_type": "table", "raw_text": "Measure | Finding\nA | B",
                                 "metadata": {"title": "WHO source", "page_number": 3, "table_data": rows}}}]
        return "Evidence [1]", results, mid
    monkeypatch.setattr(main, "generate_answer_with_memory", generate)
    client = TestClient(main.app)
    sid = create_session(pg_conn)
    response = client.post("/chat", json={"session_id": sid, "message": "Compare findings"})
    assert response.status_code == 200
    history = client.get(f"/sessions/{sid}").json()["messages"]
    assert history[-1]["citations"] == response.json()["citations"]
    assert history[-1]["citations"][0]["table"]["rows"] == rows
