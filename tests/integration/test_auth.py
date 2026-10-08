"""Private-account API behavior with the isolated test PostgreSQL database."""
import importlib
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from medrag.api.auth import password_matches, rate_limit
from medrag.memory.chat_memory import create_session

main = importlib.import_module("medrag.api.main")
pytestmark = pytest.mark.integration


@pytest.fixture
def private_api(pg_conn, make_pool, monkeypatch):
    monkeypatch.setattr(main.settings, "auth_required", True)
    monkeypatch.setattr(main.app.state, "pg_pool", make_pool(maxconn=4), raising=False)
    with pg_conn.cursor() as cur:
        cur.execute("DELETE FROM request_limits")
    return TestClient(main.app), pg_conn


def register(client):
    username = "user_" + uuid.uuid4().hex[:12]
    password = "Long-test-password-123!"
    response = client.post("/auth/register", json={"username": username, "password": password})
    assert response.status_code == 200
    token = response.json()["access_token"]
    client.cookies.clear()  # these existing tests exercise explicit bearer auth
    return SimpleNamespace(username=username, password=password, token=token, headers={"Authorization": f"Bearer {token}"})


def test_private_chats_and_all_session_routes_enforce_ownership(private_api):
    client, conn = private_api
    # Historical unowned sessions must not be claimed by a new account.
    legacy = create_session(conn, title="Legacy")
    alice, bob = register(client), register(client)
    sid = client.post("/sessions", json={"title": "Private"}, headers=alice.headers).json()["session_id"]
    assert [s["session_id"] for s in client.get("/sessions", headers=alice.headers).json()["sessions"]] == [sid]
    assert client.get("/sessions", headers=bob.headers).json()["sessions"] == []
    assert client.get(f"/sessions/{sid}", headers=alice.headers).status_code == 200
    assert client.get(f"/sessions/{legacy}", headers=alice.headers).status_code == 404
    assert client.get(f"/sessions/{sid}", headers=bob.headers).status_code == 404
    assert client.post("/chat", json={"session_id": sid, "message": "Q?"}, headers=bob.headers).status_code == 404
    assert client.post(f"/sessions/{sid}/documents", files={"file": ("x.pdf", b"bytes", "application/pdf")}, headers=bob.headers).status_code == 404
    assert client.get("/sessions").status_code == 401
    assert client.get("/sessions", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_password_storage_login_and_revocable_expiring_tokens(private_api):
    client, conn = private_api
    account = register(client)
    with conn.cursor() as cur:
        cur.execute("SELECT password_hash FROM accounts WHERE username = %s", (account.username,))
        digest = cur.fetchone()[0]
        assert account.password not in digest
        assert password_matches(account.password, digest)
        cur.execute("SELECT count(*) FROM auth_tokens WHERE token_hash = %s", (account.token,))
        assert cur.fetchone()[0] == 0
    wrong = client.post("/auth/login", json={"username": account.username, "password": "incorrect-password"})
    unknown = client.post("/auth/login", json={"username": "unknown_" + uuid.uuid4().hex[:10], "password": "incorrect-password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    login = client.post("/auth/login", json={"username": account.username.upper(), "password": account.password})
    assert login.status_code == 200
    assert client.post("/auth/logout", headers=account.headers).status_code == 200
    assert client.get("/sessions", headers=account.headers).status_code == 401
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    with conn.cursor() as cur:
        cur.execute("UPDATE auth_tokens SET expires_at = now() - interval '1 second'")
    assert client.get("/sessions", headers=headers).status_code == 401


def test_login_attempts_are_rate_limited(private_api, monkeypatch):
    monkeypatch.setattr(main.auth.time, "time", lambda: 123480.0)
    client, _ = private_api
    for _ in range(5):
        assert client.post("/auth/login", json={"username": "unknown", "password": "incorrect-password"}).status_code == 401
    limited = client.post("/auth/login", json={"username": "unknown", "password": "incorrect-password"})
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


def test_browser_cookie_survives_refresh_and_logout_revokes_it(private_api):
    client, _ = private_api
    account = register(client)
    login = client.post("/auth/login", json={"username": account.username, "password": account.password})
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=" in cookie
    token = client.cookies.get("medrag_session")
    # A new browser connection retains its cookie across a page refresh.
    refreshed = TestClient(main.app)
    refreshed.cookies.set("medrag_session", token)
    assert refreshed.get("/sessions").status_code == 200
    assert refreshed.post("/auth/logout", headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert refreshed.get("/sessions", headers={"Authorization": "Bearer forged"}).status_code == 401
    logout = refreshed.post("/auth/logout")
    assert logout.status_code == 200
    assert "Max-Age=0" in logout.headers["set-cookie"]
    refreshed.cookies.set("medrag_session", token)
    assert refreshed.get("/sessions").status_code == 401


def test_expired_cookie_cannot_restore_login(private_api):
    client, conn = private_api
    account = register(client)
    client.cookies.set("medrag_session", account.token)
    with conn.cursor() as cur:
        cur.execute("UPDATE auth_tokens SET expires_at = now() - interval '1 second'")
    assert client.get("/sessions").status_code == 401


def test_chat_and_upload_budgets_use_shared_database_state(private_api):
    client, conn = private_api
    account = register(client)
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM accounts WHERE username = %s", (account.username,))
        uid = str(cur.fetchone()[0])
    for _ in range(10):
        rate_limit(conn, f"chat:{uid}", 10)
    response = client.post("/chat", json={"session_id": str(uuid.uuid4()), "message": "Q?"}, headers=account.headers)
    assert response.status_code == 429


def test_uploaded_file_registry_is_private_and_survives_new_connections(private_api):
    client,conn=private_api
    alice,bob=register(client),register(client)
    sid=client.post("/sessions",json={},headers=alice.headers).json()["session_id"]
    document_id=str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute("INSERT INTO uploaded_documents(document_id,session_id,content_hash,filename,chunk_count) VALUES(%s,%s,%s,%s,%s)",
                    (document_id,sid,"synthetic-test-hash","portfolio-test.pdf",1))
    refreshed=TestClient(main.app)
    response=refreshed.get(f"/sessions/{sid}/documents",headers=alice.headers)
    assert response.status_code==200
    assert response.json()=={"documents":[{"document_id":document_id,"filename":"portfolio-test.pdf","chunk_count":1}]}
    assert refreshed.get(f"/sessions/{sid}/documents",headers=bob.headers).status_code==404
    assert refreshed.get(f"/sessions/{sid}/documents").status_code==401
