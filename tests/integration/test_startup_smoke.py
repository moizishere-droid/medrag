"""Real API lifespan and private routes using only the isolated test database."""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

from config.settings import settings

main = importlib.import_module("medrag.api.main")
pytestmark = pytest.mark.integration


def test_real_startup_health_and_authenticated_session(pg_conn, monkeypatch):
    # Lifespan owns its own clients/pool. Only PostgreSQL writes occur, and
    # they must be directed at the guarded fixture's dedicated test database.
    dbname = pg_conn.get_dsn_parameters()["dbname"]
    assert dbname == "medrag_chat_test"
    monkeypatch.setattr(settings, "postgres_db", dbname)
    monkeypatch.setattr(settings, "auth_required", True)
    with pg_conn.cursor() as cur:
        cur.execute("DELETE FROM request_limits")
    with TestClient(main.app) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/sessions").status_code == 401
        response = client.post("/auth/register", json={"username": "smoke_" + uuid.uuid4().hex[:12], "password": "Long-test-password-123!"})
        assert response.status_code == 200
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        created = client.post("/sessions", json={"title": "Startup smoke"}, headers=headers)
        assert created.status_code == 200
        sid = created.json()["session_id"]
        assert client.get(f"/sessions/{sid}", headers=headers).json()["messages"] == []


def test_onnx_reranker_matches_torch_for_mixed_lengths(tmp_path):
    import numpy as np
    from sentence_transformers import CrossEncoder
    from medrag.retrieval.reranking import CROSS_ENCODER_MODEL
    from medrag.retrieval.onnx_reranker import OnnxReranker
    encoder = CrossEncoder(CROSS_ENCODER_MODEL, device="cpu")
    pairs = [["hypertension", "High blood pressure is hypertension."],
             ["hypertension treatment", "A tyre is made of rubber."],
             ["blood pressure", "Clinical guidance describes blood pressure monitoring and treatment goals. " * 12]]
    expected = encoder.predict(pairs, show_progress_bar=False)
    exported = OnnxReranker(encoder, tmp_path)
    np.testing.assert_allclose(exported.predict(pairs), expected, rtol=1e-4, atol=1e-4)
    np.testing.assert_allclose(exported.predict(pairs[:1]), expected[:1], rtol=1e-4, atol=1e-4)
