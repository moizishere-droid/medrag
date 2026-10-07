"""Streamlit state transitions with an offline HTTP backend."""
from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest


def test_source_table_and_figure_render_after_history_reload(monkeypatch):
    import io
    import requests
    from PIL import Image
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, format="PNG")
    calls = []
    citation = {"marker": 1, "chunk_id": "table", "source": "who", "source_id": "diabetes",
                "title": "WHO evidence", "url": None,
                "table": {"rows": [["Treatment", "Evidence"], ["A", "B"]], "page_number": 2},
                "images": [{"filename": "figure.png", "page_number": 4, "figure_number": "1"}]}
    def response(data):
        return SimpleNamespace(json=lambda: data, raise_for_status=lambda: None, status_code=200)
    monkeypatch.setattr("requests.get", lambda *a, **k: response({"required": False}))
    def request(method, url, **kwargs):
        if "/media/who/" in url:
            calls.append(url)
            return SimpleNamespace(content=image.getvalue(), raise_for_status=lambda: None, status_code=200)
        if url.endswith("/health"):
            return response({"status": "ok", "dependencies": {"postgres": "ok"}})
        if url.endswith("/sessions"):
            return response({"sessions": [{"session_id": "a", "title": "Evidence"}]})
        return response({"messages": [{"role": "assistant", "content": "Answer [1]", "citations": [citation]}]})
    monkeypatch.setattr("requests.request", request)
    path = Path(__file__).resolve().parents[2] / "frontend" / "streamlit_app.py"
    app = AppTest.from_file(str(path)).run()
    assert not app.exception
    assert len(app.dataframe) == 1
    assert app.dataframe[0].value.iloc[1, 0] == "A"
    assert len(app.image) == 1
    assert "PDF page 5" in app.image[0].captions[0]
    assert len(calls) == 1
    assert any("PDF page 3" in c.value for c in app.caption)
    # An unavailable media file must not erase the answer or source table.
    original = request
    def unavailable(method, url, **kwargs):
        if "/media/who/" in url:
            raise requests.ConnectionError("offline")
        return original(method, url, **kwargs)
    monkeypatch.setattr("requests.request", unavailable)
    app.run()
    assert not app.exception and len(app.dataframe) == 1
    assert any("temporarily unavailable" in warning.value for warning in app.warning)


def test_unavailable_backend_can_be_retried(monkeypatch):
    import requests
    monkeypatch.setattr("requests.get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("not ready")))
    path = Path(__file__).resolve().parents[2] / "frontend" / "streamlit_app.py"
    app = AppTest.from_file(str(path)).run()
    assert not app.exception
    assert app.button[0].label == "Retry connection"
    monkeypatch.setattr("requests.get", lambda *a, **k: SimpleNamespace(json=lambda: {"required": True}, raise_for_status=lambda: None))
    monkeypatch.setattr("requests.request", lambda *a, **k: SimpleNamespace(json=lambda: {"sessions": []}, raise_for_status=lambda: None, status_code=200))
    app.button[0].click().run(timeout=15)
    assert not app.exception
    assert "MedRAG" in app.title[0].value
    assert not any("temporarily unavailable" in warning.value for warning in app.warning)


def test_question_is_drawn_before_request_and_sources_are_grouped(monkeypatch):
    import streamlit as st
    events = []
    original_write = st.write
    def write(value, *args, **kwargs):
        if value == "What is diabetes?":
            events.append("draw")
        return original_write(value, *args, **kwargs)
    monkeypatch.setattr(st, "write", write)
    def response(data):
        return SimpleNamespace(json=lambda: data, raise_for_status=lambda: None, status_code=200)
    monkeypatch.setattr("requests.get", lambda *a, **k: response({"required": False, "dependencies": {"postgres": "ok"}}))
    def request(method, url, **kwargs):
        if url.endswith("/chat"):
            assert events == ["draw"]
            events.append("request")
            citations = [dict(marker=n, source="user_upload", source_id="doc", title="diabetes.pdf", url=None) for n in (1, 2)]
            return response({"answer": "Answer [1][2]", "citations": citations})
        return response({"sessions": []})
    monkeypatch.setattr("requests.request", request)
    path = Path(__file__).resolve().parents[2] / "frontend" / "streamlit_app.py"
    app = AppTest.from_file(str(path))
    app.session_state.current_session_id = "a"
    app.session_state.messages = []
    app.run()
    app.chat_input[0].set_value("What is diabetes?").run()
    assert not app.exception
    assert events[:2] == ["draw", "request"]
    assert app.expander[0].label == "Sources (1)"
    assert sum("diabetes.pdf" in m.value for m in app.markdown) == 1


def test_session_switch_loads_correct_history_and_scopes_upload_picker(monkeypatch):
    sessions = [{"session_id": sid, "title": "Same title", "created_at": "2026-10-06"} for sid in ("a", "b")]
    def response(data):
        return SimpleNamespace(json=lambda: data, raise_for_status=lambda: None, status_code=200)
    monkeypatch.setattr("requests.get", lambda *a, **k: response({"required": False}))
    def request(method, url, **kwargs):
        if url.endswith("/health"):
            return response({"status": "ok", "dependencies": {"postgres": "ok", "qdrant": "ok", "neo4j": "ok"}})
        if url.endswith("/sessions"):
            return response({"sessions": sessions})
        sid = url.rsplit("/", 1)[-1]
        return response({"messages": [{"role": "user", "content": f"History {sid}"}]})
    monkeypatch.setattr("requests.request", request)
    path = Path(__file__).resolve().parents[2] / "frontend" / "streamlit_app.py"
    app = AppTest.from_file(str(path)).run()
    assert not app.exception
    assert app.session_state.current_session_id == "a"
    assert len(set(app.sidebar.selectbox[0].options)) == 2
    assert "pdf_upload:a" in app.get("file_uploader")[0].proto.id
    assert app.sidebar.expander[0].label == "Supported topics and sources (36 topics)"
    panel = " ".join(m.value for m in app.sidebar.markdown)
    assert all(source in panel for source in ("PubMed", "OpenFDA", "WHO"))
    assert "- Diabetes" in panel and "- Malnutrition" in panel
    app.sidebar.selectbox[0].select("b").run()
    assert not app.exception
    assert app.session_state.current_session_id == "b"
    assert app.session_state.messages == [{"role": "user", "content": "History b"}]
    assert "pdf_upload:b" in app.get("file_uploader")[0].proto.id


def test_submission_survives_sidebar_rerun_and_updates_topic(monkeypatch):
    import streamlit as st
    calls = []
    sessions = [{"session_id": "a", "title": None}, {"session_id": "b", "title": None}]
    def response(data):
        return SimpleNamespace(json=lambda: data, raise_for_status=lambda: None, status_code=200)
    monkeypatch.setattr("requests.get", lambda *a, **k: response({"required": False, "dependencies": {"postgres": "ok"}}))
    interrupted = False
    def request(method, url, **kwargs):
        nonlocal interrupted
        if url.endswith("/sessions"):
            if st.session_state.get("pending_question") and not interrupted:
                interrupted = True
                st.rerun()  # formerly swallowed the chat widget's submission
            return response({"sessions": sessions})
        if url.endswith("/chat"):
            calls.append(kwargs["json"])
            sessions[0]["title"] = "Diabetes Type 2"
            return response({"answer": "Answer", "citations": []})
        return response({"messages": []})
    monkeypatch.setattr("requests.request", request)
    path = Path(__file__).resolve().parents[2] / "frontend" / "streamlit_app.py"
    app = AppTest.from_file(str(path)).run(timeout=15)
    app.chat_input[0].set_value("What is type 2 diabetes?").run(timeout=15)
    assert not app.exception
    assert calls == [{"session_id": "a", "message": "What is type 2 diabetes?"}]
    assert [m["content"] for m in app.session_state.messages] == ["What is type 2 diabetes?", "Answer"]
    assert app.sidebar.selectbox[0].value == "a"
    assert "Diabetes Type 2" in app.sidebar.selectbox[0].options


def test_interrupted_session_read_recovers_then_preserves_cached_chats(monkeypatch):
    import requests
    sessions = [{"session_id": "a", "title": "Diabetes"}]
    attempts = []
    failing = False
    def response(data):
        return SimpleNamespace(json=lambda: data, raise_for_status=lambda: None, status_code=200)
    monkeypatch.setattr("requests.get", lambda *a, **k: response({"required": False, "dependencies": {"postgres": "ok"}}))
    def request(method, url, **kwargs):
        if url.endswith("/sessions"):
            attempts.append(url)
            if failing or len(attempts) == 1:
                raise requests.ConnectionError("RemoteDisconnected")
            return response({"sessions": sessions})
        return response({"messages": []})
    monkeypatch.setattr("requests.request", request)
    path = Path(__file__).resolve().parents[2] / "frontend" / "streamlit_app.py"
    app = AppTest.from_file(str(path)).run(timeout=15)
    assert not app.exception
    assert len(attempts) >= 2
    failing = True
    app.run(timeout=15)
    assert not app.exception
    assert app.sidebar.selectbox[0].value == "a"
    assert any(b.label == "Retry loading chats" for b in app.sidebar.button)
    assert not any("No sessions yet" in message.value for message in app.sidebar.info)
