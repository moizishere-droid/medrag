import streamlit as st
import requests
import os
import time
import uuid
import sys
from pathlib import Path
from collections import Counter
import streamlit.components.v1 as components
from medrag.citations.citations import group_citations_by_source
from medrag.memory.session_titles import title_from_query
sys.path.insert(0, str(Path(__file__).parent))
from interface import apply_theme, navbar, landing, account_form, topics, navigate, show_auth_feedback

# Direct IPv4 avoids intermittent localhost resolution/disconnects on Windows.
# Browser auth keeps the UI hostname so its HttpOnly cookie reaches Streamlit.
API_URL = os.environ.get("MEDRAG_API_URL", "http://127.0.0.1:8000").rstrip("/")
BROWSER_API_URL = os.environ.get("MEDRAG_BROWSER_API_URL", os.environ.get("MEDRAG_API_URL", "http://localhost:8000")).rstrip("/")
auth_bridge = components.declare_component("medrag_auth", path=str(Path(__file__).parent / "auth_bridge"))

st.set_page_config(page_title="MedRAG · Research workspace", page_icon="✦", layout="wide", initial_sidebar_state="auto")
apply_theme()


def public_status(path, ttl=30):
    """Keep repeated sidebar status checks off the critical chat path.

    Only public config/health responses are cached, in this browser session.
    Private session lists and chat evidence are always fetched fresh.
    """
    cache = st.session_state.setdefault("public_status_cache", {})
    key = (API_URL, path)
    cached = cache.get(key)
    if cached and time.monotonic() - cached[0] < ttl:
        return cached[1]
    response = requests.get(f"{API_URL}{path}", timeout=5)
    if not (path == "/health" and response.status_code == 503):
        response.raise_for_status()
    data = response.json()
    cache[key] = (time.monotonic(), data)
    return data

try:
    auth_required = public_status("/auth/config")["required"]
except (requests.exceptions.RequestException, KeyError) as exc:
    st.warning("The backend is starting or temporarily unavailable. Wait a moment, then retry.")
    if st.button("Retry connection"):
        st.session_state.pop("public_status_cache", None)
        st.rerun()
    with st.expander("Connection details"):
        st.caption(f"API address: {API_URL}")
        st.text(str(exc))
    st.stop()


def clear_login():
    st.session_state.pop("public_status_cache", None)
    keys = {"access_token", "username", "current_session_id", "messages", "last_uploaded_key", "pending_question", "pending_files", "selected_session_id", "topic_titles", "session_titles", "last_known_sessions", "sessions_load_failed"}
    keys.update(key for key in st.session_state if key.startswith("pdf_upload:"))
    for key in keys:
        st.session_state.pop(key, None)


restored_cookie = st.context.cookies.get("medrag_session")
if (not st.session_state.get("ignore_cookie") and not st.session_state.get("access_token")
        and isinstance(restored_cookie, str) and restored_cookie and len(restored_cookie) <= 128):
    st.session_state.access_token = restored_cookie

# Keep a stable root position even when no authentication request is pending.
# Inserting the iframe above an existing form shifts Streamlit element paths
# and briefly leaves the previous page visible above the newly rendered page.
auth_transport = st.container(key="auth_transport")
if pending := st.session_state.get("auth_action"):
    with auth_transport:
        result = auth_bridge(api_url=BROWSER_API_URL, default=None, key=pending["nonce"], **pending)
    if result:
        st.session_state.pop("auth_action", None)
        if result.get("error"):
            st.session_state.auth_feedback = {
                "title": "Unable to sign out" if pending["action"] == "logout" else "Unable to sign in" if pending["action"] == "login" else "Unable to create account",
                "message": result["error"], "success": False,
            }
            st.rerun()
        else:
            clear_login()
            st.query_params.clear()
            st.query_params["page"] = "overview" if pending["action"] == "logout" else "workspace"
            if pending["action"] == "logout":
                st.session_state.ignore_cookie = True
            else:
                token = result.get("access_token")
                if not isinstance(token, str) or not token or len(token) > 128:
                    st.session_state.auth_feedback = {"title": "Unable to sign in", "message": "Sign-in could not be restored. Please try again.", "success": False}
                    st.rerun()
                st.session_state.access_token = token
                st.session_state.ignore_cookie = False
                st.session_state.auth_feedback = {
                    "title": "Account created" if pending["action"] == "register" else "Welcome back",
                    "message": "You are signed in. Your research workspace is ready.", "success": True,
                }
            st.rerun()


if auth_required and not st.session_state.get("access_token"):
    page = st.query_params.get("page", "overview")
    if page not in {"overview", "login", "signup"}:
        page = "login"
        st.query_params["page"] = page
    navbar()
    if page == "overview":
        landing()
    else:
        action = account_form(page)
        if action:
            st.session_state.auth_action = {**action, "nonce": uuid.uuid4().hex}
            st.rerun()
    show_auth_feedback()
    st.stop()


def api_request(method, url, *, retry_reads=True, **kwargs):
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"} if st.session_state.get("access_token") else {}
    # Interrupted reads can be retried safely. Never replay chat/upload/create
    # writes: the server may already have committed them before disconnecting.
    attempts = 3 if method == "GET" and retry_reads else 1
    for attempt in range(attempts):
        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            if method == "GET" and response.status_code in {502, 503, 504} and attempt + 1 < attempts:
                time.sleep(0.2 * (attempt + 1))
                continue
            break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt + 1 == attempts:
                raise
            time.sleep(0.2 * (attempt + 1))
    if response.status_code == 401 and auth_required:
        clear_login()
        st.session_state.ignore_cookie = True
        st.rerun()
    return response


def api_get(url, **kwargs):
    return api_request("GET", url, **kwargs)


def api_post(url, **kwargs):
    return api_request("POST", url, **kwargs)


def sign_out():
    st.session_state.auth_action = {"action": "logout", "nonce": uuid.uuid4().hex}
    st.rerun()


st.query_params["page"] = "workspace"
navbar(authenticated=True, sign_out=sign_out if auth_required else None)
workspace_view = st.query_params.get("view", "chat")
if workspace_view not in {"chat", "topics"}:
    workspace_view = "chat"
    st.query_params["view"] = "chat"

# --- session state init ---
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- sidebar: title + health check ---
st.sidebar.title("Research workspace")
if st.sidebar.button("Research chat", use_container_width=True, type="primary" if workspace_view == "chat" else "secondary"):
    navigate("workspace", "chat")
if st.sidebar.button("Topics & sources", use_container_width=True, type="primary" if workspace_view == "topics" else "secondary"):
    navigate("workspace", "topics")

st.sidebar.divider()

# --- sidebar: session switcher + new session ---
def load_sessions():
    try:
        resp = api_get(f"{API_URL}/sessions", timeout=5)
        resp.raise_for_status()
        sessions = resp.json().get("sessions", [])
        st.session_state.last_known_sessions = sessions
        st.session_state.sessions_load_failed = False
        return sessions
    except requests.exceptions.RequestException as e:
        st.session_state.sessions_load_failed = True
        st.sidebar.warning("Your chats could not be loaded. The backend connection was interrupted.")
        if st.sidebar.button("Retry loading chats"):
            st.rerun()
        return st.session_state.get("last_known_sessions", [])


def session_label(s):
    if s.get("title"):
        return s["title"]
    return st.session_state.get("topic_titles", {}).get(s["session_id"], "New Chat")


if st.sidebar.button("＋ New conversation", use_container_width=True):
    try:
        resp = api_post(f"{API_URL}/sessions", json={}, timeout=10)
        resp.raise_for_status()
        new_session = resp.json()
        st.session_state.current_session_id = new_session["session_id"]
        st.session_state.selected_session_id = new_session["session_id"]
        st.session_state.messages = []
        st.query_params["chat"] = new_session["session_id"]
        st.query_params["view"] = "chat"
        st.rerun()
    except requests.exceptions.RequestException as e:
        st.sidebar.error(f"Session creation failed: {e}")

sessions = load_sessions()
if sessions:
    # Stable IDs prevent renamed/reordered session dictionaries from resetting
    # the widget and loading an empty history during a chat-input submission.
    by_id = {s["session_id"]: s for s in sessions}
    st.session_state.session_titles = {sid: s.get("title") for sid, s in by_id.items()}
    base_labels = {sid: session_label(s) for sid, s in by_id.items()}
    counts = Counter(base_labels.values())
    # Streamlit serializes selectbox values by formatted text, even with ID
    # options. Every displayed label must therefore be unique.
    labels = {}
    for sid, label in base_labels.items():
        peers = sorted(key for key, value in base_labels.items() if value == label)
        labels[sid] = f"{label} ({peers.index(sid) + 1})" if counts[label] > 1 else label
    pending_sid = st.session_state.get("pending_question", {}).get("session_id")
    if pending_sid in by_id:
        st.session_state.selected_session_id = pending_sid
    if st.session_state.get("selected_session_id") not in by_id:
        current = st.session_state.current_session_id
        restored_chat = st.query_params.get("chat")
        st.session_state.selected_session_id = (current if current in by_id else
                                               restored_chat if restored_chat in by_id else next(iter(by_id)))
    selected_id = st.sidebar.selectbox(
        "Session",
        list(by_id),
        key="selected_session_id",
        format_func=lambda sid: labels[sid],
    )

    if selected_id != st.session_state.current_session_id:
        try:
            history_resp = api_get(f"{API_URL}/sessions/{selected_id}", timeout=5)
            history_resp.raise_for_status()
            messages = history_resp.json().get("messages", [])
            st.session_state.current_session_id = selected_id
            st.session_state.messages = messages
            st.query_params["chat"] = selected_id
            st.rerun()
        except requests.exceptions.RequestException as e:
            st.sidebar.error(f"Session load failed: {e}")
else:
    if not st.session_state.get("sessions_load_failed"):
        st.sidebar.info("No sessions yet — create one above.")

st.sidebar.divider()

# Uploaded evidence remains scoped to the selected conversation.
if st.session_state.current_session_id is not None:
    try:
        uploaded_response = api_get(f"{API_URL}/sessions/{st.session_state.current_session_id}/documents", timeout=5)
        uploaded_response.raise_for_status()
        uploaded_documents = uploaded_response.json().get("documents", [])
        if uploaded_documents:
            st.sidebar.caption("PDFs already indexed in this chat")
            for document in uploaded_documents:
                st.sidebar.text(f"{document['filename']} ({document['chunk_count']} chunks)")
            st.sidebar.caption("These files remain available after refresh or sign-out when you return to this chat.")
    except requests.exceptions.RequestException:
        st.sidebar.warning("The indexed PDF list is temporarily unavailable. This does not mean your files were deleted.")

# --- main area ---
if workspace_view == "topics":
    topics()
    show_auth_feedback()
    st.stop()

st.html('<div class="mr-eyebrow">PERSONAL RESEARCH WORKSPACE</div>')
st.title("MedRAG · Research chat")
st.caption("Ask in your language · Attach a PDF using + · Review the cited evidence")
st.divider()

if st.session_state.current_session_id is None and not st.session_state.get("pending_question"):
    st.info("What would you like to research? Send a question or attach a PDF to start a conversation.")
with st.container(key="research_chat"):
    # The callback runs before sidebar/history code can trigger a rerun. Keep
    # submissions outside the ephemeral chat widget event until processed.
    def capture_question():
        submitted = st.session_state.get("chat_prompt", "")
        prompt = (submitted if isinstance(submitted, str) else submitted.text).strip()
        files = [] if isinstance(submitted, str) else submitted.files
        if prompt or files:
            sid = st.session_state.current_session_id
            st.session_state.pending_question = {"session_id": sid, "message": prompt}
            st.session_state.pending_files = [
                {"name": file.name, "bytes": file.getvalue(), "id": file.file_id} for file in files
            ]
            if not st.session_state.get("session_titles", {}).get(sid):
                st.session_state.setdefault("topic_titles", {}).setdefault(sid, title_from_query(prompt))

    def render_source_visuals(citations):
        tables_seen, images_seen = set(), set()
        for citation in citations:
            marker = f"[{citation['marker']}]"
            title = citation["title"]
            table = citation.get("table")
            if citation.get("table_warning"):
                st.warning(f"Source table {marker}: {citation['table_warning']}")
            if table and citation["chunk_id"] not in tables_seen:
                tables_seen.add(citation["chunk_id"])
                with st.expander(f"Original source excerpt {marker} — {title}", expanded=True):
                    if table.get("page_number") is not None:
                        st.caption(f"PDF page {table['page_number'] + 1}")
                    if table.get("part"):
                        st.caption(f"Table part {table['part']}")
                    rows = table["rows"]
                    width = max((len(row) for row in rows), default=0)
                    st.caption("Original source language; not translated. This is a retrieved extract, not the full PDF.")
                    if width == 1:
                        for row in rows:
                            if row and row[0]:
                                st.text(row[0])
                    elif width:
                        columns = {f"Column {i + 1}": [row[i] if i < len(row) else "" for row in rows]
                                   for i in range(width)}
                        st.table(columns)
                    st.caption("All extracted rows are shown. Scroll to read the remaining content; check the cited PDF for original formatting.")
            for image in citation.get("images", []):
                filename = image["filename"]
                if filename in images_seen:
                    continue
                images_seen.add(filename)
                with st.expander(f"Source figure {marker} — {title}", expanded=True):
                    if image.get("caption"):
                        st.caption(image["caption"])
                    caption = f"{marker} {title}"
                    if image.get("figure_number"):
                        caption += f" — Figure {image['figure_number']}"
                    if image.get("page_number") is not None:
                        caption += f" — PDF page {image['page_number'] + 1}"
                    if image.get("image_type") == "rasterized_page":
                        caption += " (source page containing the figure)"
                    try:
                        # Fetch through the authenticated API; Streamlit sends
                        # image bytes to the browser, never the bearer token.
                        response = api_get(f"{API_URL}/media/who/{filename}", timeout=5, retry_reads=False)
                        response.raise_for_status()
                        st.image(response.content, caption=caption)
                    except requests.exceptions.RequestException:
                        st.warning("This source figure is temporarily unavailable. The answer and citations are still available.")

    # render existing messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("citations"):
                render_source_visuals(msg["citations"])
                sources = group_citations_by_source(msg["citations"])
                st.caption("Supporting evidence")
                with st.expander(f"Sources ({len(sources)})"):
                    for c in sources:
                        markers = ", ".join(f"[{marker}]" for marker in c["markers"])
                        source_name = {"user_upload": "Uploaded document", "who": "WHO", "pubmed": "PubMed", "openfda": "FDA label"}.get(c["source"], c["source"])
                        st.markdown(f"**{markers}** {c['title']} — *{source_name}*")
                        if c.get("url"):
                            st.markdown(f"[{c['url']}]({c['url']})")

    # Draw the incoming turn above the composer before waiting on any service.
    # Reserve its response slot here so later loading content stays above input.
    pending = st.session_state.get("pending_question")
    loading = bool(pending and pending["session_id"] == st.session_state.current_session_id)
    if loading and pending["message"]:
        with st.chat_message("user"):
            st.write(pending["message"])
    upload_feedback = st.container()
    response_slot = st.empty()
    if loading and pending["message"]:
        with response_slot.container():
            assistant_output = st.chat_message("assistant")

    # The input stays below the current turn, including while its answer loads.
    st.chat_input("Ask a research question…", key="chat_prompt", on_submit=capture_question,
                  accept_file=True, file_type=["pdf"], max_upload_size=20, disabled=loading)
    st.caption("Educational research demo. Not a substitute for medical care. Check original sources.")
    pending = st.session_state.get("pending_question")
    if pending and pending["session_id"] == st.session_state.current_session_id:
        prompt = pending["message"]
        if st.session_state.current_session_id is None:
            try:
                response = api_post(f"{API_URL}/sessions", json={}, timeout=10)
                response.raise_for_status()
                sid = response.json()["session_id"]
                st.session_state.current_session_id = sid
                st.session_state.selected_session_id = sid
                pending["session_id"] = sid
                st.query_params["chat"] = sid
            except requests.exceptions.RequestException:
                st.session_state.pop("pending_question", None)
                st.session_state.pop("pending_files", None)
                st.error("Could not start a conversation. Please try again.")
                response_slot.empty()
                if st.button("Return to chat"):
                    st.rerun()
                st.stop()
        for file in st.session_state.pop("pending_files", []):
            file_key = f"{st.session_state.current_session_id}:{file['id']}"
            if st.session_state.get("last_uploaded_key") == file_key:
                continue
            with upload_feedback, st.status("Uploading and indexing your PDF…", expanded=False):
                try:
                    response = api_post(
                        f"{API_URL}/sessions/{st.session_state.current_session_id}/documents",
                        files={"file": (file["name"], file["bytes"], "application/pdf")}, timeout=120,
                    )
                    response.raise_for_status()
                    st.session_state.last_uploaded_key = file_key
                    st.success(f"{file['name']} is ready in this conversation.")
                except requests.exceptions.RequestException:
                    st.session_state.pop("pending_question", None)
                    st.error("The PDF could not be indexed. Attach it again before asking about it.")
                    if prompt:
                        st.info(f"Your unsent question: {prompt}")
                    response_slot.empty()
                    if st.button("Return to chat"):
                        st.rerun()
                    st.stop()
        st.session_state.pop("pending_question", None)
        if not prompt:
            st.rerun()
        st.session_state.messages.append(
            {"role": "user", "content": prompt, "citations": None}
        )
        with assistant_output, st.spinner("Researching your question…"):
            try:
                resp = api_post(
                    f"{API_URL}/chat",
                    json={
                        "session_id": st.session_state.current_session_id,
                        "message": prompt,
                    },
                    timeout=90,
                )
                resp.raise_for_status()
                data = resp.json()
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": data["answer"],
                        "citations": data.get("citations", []),
                    }
                )
            except requests.exceptions.RequestException as e:
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": ("The answer service timed out. Your question is still visible. Check chat history before retrying; the request may have completed."
                                    if isinstance(e, requests.exceptions.Timeout) else
                                    "The answer service is temporarily unavailable. Your question is still visible. Please try again later."),
                        "citations": None,
                    }
                )
        st.rerun()

show_auth_feedback()
