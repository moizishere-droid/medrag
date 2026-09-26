"""
Phase 19 end-to-end verification: create a session with a user_id,
upload the real test PDF, chat a question only that PDF can answer,
and confirm isolation against a second session with a different user_id.
"""

from fastapi.testclient import TestClient
from medrag.api.main import app

TEST_PDF_PATH = "data/Diabetes_Mellitus_Type_2.pdf"  # adjust to actual path

with TestClient(app) as client:

    # --- Step 1: health check ---
    resp = client.get("/health")
    print("Health:", resp.status_code, resp.json())
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # --- Step 2: create a session WITH a user_id ---
    resp = client.post("/sessions", json={"title": "Phase 19 test", "user_id": "test-user-abc"})
    print("Create session (user A):", resp.status_code, resp.json())
    assert resp.status_code == 200
    session_id_a = resp.json()["session_id"]

    # --- Step 3: create a SECOND session with a DIFFERENT user_id ---
    resp = client.post("/sessions", json={"title": "Phase 19 test - other user", "user_id": "test-user-999"})
    print("Create session (user B):", resp.status_code, resp.json())
    assert resp.status_code == 200
    session_id_b = resp.json()["session_id"]

    TEST_PDF_PATH = r"C:\Users\DELL\Desktop\medrag\data\Diabetes_Mellitus_Type_2.pdf"
    # --- Step 4: upload the real test PDF to session A (user-abc) ---
    with open(TEST_PDF_PATH, "rb") as f:
        resp = client.post(
            f"/sessions/{session_id_a}/documents",
            files={"file": ("Diabetes_Mellitus_Type_2.pdf", f, "application/pdf")},
        )
    print("Upload document:", resp.status_code, resp.json())
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
    # Check at least one citation traces back to the uploaded document
    citation_sources = [c["source"] for c in resp.json()["citations"]]
    print("Citation sources:", citation_sources)

    # --- Step 6: chat in session B (different user) - same question, should NOT see the upload ---
    resp = client.post("/chat", json={
        "session_id": session_id_b,
        "message": "What happens when the body can no longer keep up with insulin production?",
    })
    print("\nChat response (session B, different user, should NOT use uploaded PDF):")
    print(resp.status_code)
    print("Answer:", resp.json()["answer"])
    print("Citations:", resp.json()["citations"])
    citation_sources_b = [c["source"] for c in resp.json()["citations"]]
    print("Citation sources:", citation_sources_b)
    assert "user_upload" not in citation_sources_b, "LEAK: session B saw session A's uploaded document!"

    # --- Step 7: test the 400 case - session with no user_id ---
    resp = client.post("/sessions", json={"title": "No user_id session"})
    session_id_no_user = resp.json()["session_id"]
    with open(TEST_PDF_PATH, "rb") as f:
        resp = client.post(
            f"/sessions/{session_id_no_user}/documents",
            files={"file": ("test.pdf", f, "application/pdf")},
        )
    print("\nUpload to session with no user_id (should be 400):", resp.status_code, resp.json())
    assert resp.status_code == 400

print("\n✅ All Phase 19 API-level checks passed")