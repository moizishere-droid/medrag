"""
Phase 19 end-to-end verification (revised for session-only isolation):
create two separate sessions, upload the real test PDF to one, chat a
question only that PDF can answer, and confirm the OTHER session
cannot see it.
"""

from fastapi.testclient import TestClient
from medrag.api.main import app

TEST_PDF_PATH = r"C:\Users\DELL\Desktop\medrag\data\Diabetes_Mellitus_Type_2.pdf"  # adjust if needed

with TestClient(app) as client:

    # --- Step 1: health check ---
    resp = client.get("/health")
    print("Health:", resp.status_code, resp.json())
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # --- Step 2: create session A ---
    resp = client.post("/sessions", json={"title": "Phase 19 test - session A"})
    print("Create session A:", resp.status_code, resp.json())
    assert resp.status_code == 200
    session_id_a = resp.json()["session_id"]

    # --- Step 3: create session B (separate, unrelated session) ---
    resp = client.post("/sessions", json={"title": "Phase 19 test - session B"})
    print("Create session B:", resp.status_code, resp.json())
    assert resp.status_code == 200
    session_id_b = resp.json()["session_id"]

    # --- Step 4: upload the real test PDF to session A ONLY ---
    with open(TEST_PDF_PATH, "rb") as f:
        resp = client.post(
            f"/sessions/{session_id_a}/documents",
            files={"file": ("Diabetes_Mellitus_Type_2.pdf", f, "application/pdf")},
        )
    print("Upload document to session A:", resp.status_code, resp.json())
    assert resp.status_code == 200
    upload_data = resp.json()
    assert upload_data["chunk_count"] > 0
    document_id = upload_data["document_id"]

    # --- Step 5: chat in session A - question only the uploaded PDF can answer ---
    resp = client.post("/chat", json={
        "session_id": session_id_a,
        "message": "What happens when the body can no longer keep up with insulin production?",
    })
    print("\nChat response (session A, should use uploaded PDF):")
    print(resp.status_code)
    print("Answer:", resp.json()["answer"])
    print("Citations:", resp.json()["citations"])
    assert resp.status_code == 200
    citation_sources_a = [c["source"] for c in resp.json()["citations"]]
    print("Citation sources (A):", citation_sources_a)
    assert "user_upload" in citation_sources_a, "Session A should see its own upload!"

    # --- Step 6: chat in session B - same question, should NOT see session A's upload ---
    resp = client.post("/chat", json={
        "session_id": session_id_b,
        "message": "What happens when the body can no longer keep up with insulin production?",
    })
    print("\nChat response (session B, separate session, should NOT use session A's upload):")
    print(resp.status_code)
    print("Answer:", resp.json()["answer"])
    print("Citations:", resp.json()["citations"])
    citation_sources_b = [c["source"] for c in resp.json()["citations"]]
    print("Citation sources (B):", citation_sources_b)
    assert "user_upload" not in citation_sources_b, "LEAK: session B saw session A's uploaded document!"

print("\n✅ All Phase 19 (session-only isolation) checks passed")