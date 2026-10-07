"""Authenticated media and citation response tests."""
import importlib

from medrag.citations.visuals import VisualCatalog

main = importlib.import_module("medrag.api.main")


def test_media_is_authenticated_and_only_serves_manifest_files(client, state, monkeypatch, tmp_path):
    import json
    import hashlib
    image_dir = tmp_path / "images" / "who"
    image_dir.mkdir(parents=True)
    (image_dir / "figure.png").write_bytes(b"png test bytes")
    (image_dir / "diabetes_metadata.jsonl").write_text(json.dumps({"filename": "figure.png", "topic": "diabetes"}))
    (image_dir / "verified_figures.jsonl").write_text(json.dumps({"filename": "figure.png", "source_id": "diabetes",
        "figure_number": "1", "caption": "Fig. 1. Evidence", "sha256": hashlib.sha256(b"png test bytes").hexdigest()}))
    catalog = VisualCatalog(tmp_path)
    monkeypatch.setattr(main, "get_visual_catalog", lambda root: catalog)
    response = client.get("/media/who/figure.png")
    assert response.status_code == 200
    assert response.content == b"png test bytes"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"].startswith("private")
    assert client.get("/media/who/unknown.png").status_code == 404
    monkeypatch.setattr(main.settings, "auth_required", True)
    # This fixture's fake cursor has no rows, including rate-limit counters.
    # Bypass only the fake limiter to exercise the real missing-token rejection.
    monkeypatch.setattr(main.auth, "rate_limit", lambda *args: None)
    assert client.get("/media/who/figure.png").status_code == 401


def test_chat_persists_visuals_and_history_returns_them(client, pipeline, db, sid):
    rows = [["Treatment", "Evidence"], ["A", "B"]]
    pipeline.answer = "Source table supports this [1]."
    pipeline.results = [{"payload": {"source": "who", "source_id": "diabetes", "chunk_id": "who_table",
                                      "chunk_type": "table", "raw_text": "Treatment | Evidence\nA | B",
                                      "metadata": {"title": "Guideline", "page_number": 1, "table_data": rows}}}]
    response = client.post("/chat", json={"session_id": sid, "message": "Compare treatments"})
    assert response.status_code == 200
    stored = pipeline.citation_updates[0][2]
    assert stored == response.json()["citations"]
    assert stored[0]["table"]["rows"] == rows
    db.history = [{"message_id": "message", "role": "assistant", "content": pipeline.answer,
                   "citations": stored, "created_at": "2026-10-07T00:00:00"}]
    assert client.get(f"/sessions/{sid}").json()["messages"][0]["citations"] == stored
