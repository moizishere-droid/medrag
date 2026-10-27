"""Reload and authentication boundaries for the redesigned Streamlit UI."""
from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[2] / "frontend" / "streamlit_app.py")


def backend(monkeypatch, cookie=True):
    import streamlit
    monkeypatch.setattr(streamlit, "context", SimpleNamespace(cookies={"medrag_session": "test-token"} if cookie else {}))
    def response(data):
        return SimpleNamespace(status_code=200, json=lambda: data, raise_for_status=lambda: None)
    monkeypatch.setattr("requests.get", lambda *a, **k: response({"required": True, "dependencies": {"postgres": "ok"}}))
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        assert kwargs["headers"]["Authorization"] == "Bearer test-token"
        if url.endswith("/sessions"):
            return response({"sessions": [{"session_id": "first", "title": "First"}, {"session_id": "second", "title": "Second"}]})
        return response({"messages": [{"role": "user", "content": "Saved question"}], "documents": []})
    monkeypatch.setattr("requests.request", request)
    return calls


def test_refresh_restores_cookie_conversation_and_workspace_section(monkeypatch):
    calls = backend(monkeypatch)
    # Fresh AppTest state represents a new browser connection after refresh.
    for _ in range(2):
        app = AppTest.from_file(APP)
        app.query_params.update({"page": "workspace", "chat": "second", "view": "topics"})
        app.run()
        assert not app.exception
        assert app.session_state.current_session_id == "second"
        assert app.query_params["view"] == ["topics"]
        assert not app.chat_input
        assert not any(b.label == "Overview" for b in app.button)
        assert any(b.label == "Sign out" for b in app.button)
        assert any(url.endswith("/sessions/second") for _, url, _ in calls)


def test_workspace_url_without_cookie_never_grants_access(monkeypatch):
    backend(monkeypatch, cookie=False)
    app = AppTest.from_file(APP)
    app.query_params.update({"page": "workspace", "chat": "second"})
    app.run()
    assert not app.exception
    assert not app.chat_input
    assert any(t.value == "Welcome back" for t in app.title)


def test_unknown_conversation_is_not_fetched(monkeypatch):
    calls = backend(monkeypatch)
    app = AppTest.from_file(APP)
    app.query_params.update({"page": "workspace", "chat": "not-owned"})
    app.run()
    assert not app.exception
    assert app.query_params["chat"] == ["first"]
    assert not any(url.endswith("/sessions/not-owned") for _, url, _ in calls)


def test_signup_password_mismatch_never_sends_credentials(monkeypatch):
    calls = backend(monkeypatch, cookie=False)
    app = AppTest.from_file(APP)
    app.query_params["page"] = "signup"
    app.run()
    app.text_input[0].set_value("researcher")
    app.text_input[1].set_value("twelve-characters")
    app.text_input[2].set_value("different-password")
    next(b for b in app.button if b.label == "Create account →").click().run()
    assert not app.exception
    assert any("do not match" in e.value for e in app.error)
    assert not calls


def test_expired_cookie_returns_to_login_without_showing_private_chat(monkeypatch):
    backend(monkeypatch)
    monkeypatch.setattr("requests.request", lambda *a, **k: SimpleNamespace(status_code=401))
    app = AppTest.from_file(APP)
    app.query_params.update({"page": "workspace", "chat": "second"})
    app.run()
    assert not app.exception
    assert not app.chat_input
    assert any(t.value == "Welcome back" for t in app.title)


def test_first_question_creates_a_conversation_before_chat(monkeypatch):
    backend(monkeypatch)
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url))
        data = {"sessions": []}
        if method == "POST" and url.endswith("/sessions"):
            data = {"session_id": "created"}
        elif url.endswith("/chat"):
            assert kwargs["json"]["session_id"] == "created"
            data = {"answer": "New answer", "citations": []}
        return SimpleNamespace(status_code=200, json=lambda: data, raise_for_status=lambda: None)
    monkeypatch.setattr("requests.request", request)
    app = AppTest.from_file(APP).run()
    app.chat_input[0].set_value("My first question").run()
    assert not app.exception
    assert calls.index(("POST", "http://127.0.0.1:8000/sessions")) < calls.index(("POST", "http://127.0.0.1:8000/chat"))
    assert app.session_state.current_session_id == "created"
    assert app.session_state.messages[-1]["content"] == "New answer"
