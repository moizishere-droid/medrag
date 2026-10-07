import streamlit as st
import requests
import os
import time
import uuid
from pathlib import Path
from collections import Counter
import streamlit.components.v1 as components
from medrag.citations.citations import group_citations_by_source
from medrag.memory.session_titles import title_from_query
from medrag.topics import TOPICS, topic_label

# Direct IPv4 avoids intermittent localhost resolution/disconnects on Windows.
# Browser auth keeps the UI hostname so its HttpOnly cookie reaches Streamlit.
API_URL = os.environ.get("MEDRAG_API_URL", "http://127.0.0.1:8000").rstrip("/")
BROWSER_API_URL = os.environ.get("MEDRAG_BROWSER_API_URL", os.environ.get("MEDRAG_API_URL", "http://localhost:8000")).rstrip("/")
auth_bridge = components.declare_component("medrag_auth", path=str(Path(__file__).parent / "auth_bridge"))

st.set_page_config(page_title="MedRAG", layout="wide")


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
    keys = {"access_token", "username", "current_session_id", "messages", "last_uploaded_key", "pending_question", "selected_session_id", "topic_titles", "session_titles", "last_known_sessions", "sessions_load_failed"}
    keys.update(key for key in st.session_state if key.startswith("pdf_upload:"))
    for key in keys:
        st.session_state.pop(key, None)


if not st.session_state.get("ignore_cookie") and not st.session_state.get("access_token") and st.context.cookies.get("medrag_session"):
    st.session_state.access_token = st.context.cookies["medrag_session"]

if pending := st.session_state.get("auth_action"):
    result = auth_bridge(api_url=BROWSER_API_URL, default=None, key=pending["nonce"], **pending)
    if result:
        st.session_state.pop("auth_action", None)
        if result.get("error"):
            st.error(result["error"])
        else:
            clear_login()
            st.info("Updating sign-in…")
            st.stop()


if auth_required and not st.session_state.get("access_token"):
    st.title("Sign in to MedRAG")
    action = st.radio("Account", ["Sign in", "Create account"], horizontal=True)
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password (at least 12 characters)", type="password", max_chars=128)
        submitted = st.form_submit_button(action)
    if submitted:
        st.session_state.auth_action = {"action": "login" if action == "Sign in" else "register",
                                       "credentials": {"username": username, "password": password},
                                       "nonce": uuid.uuid4().hex}
        st.rerun()
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


if auth_required:
    st.sidebar.caption("Signed in")
    if st.sidebar.button("Sign out"):
        st.session_state.auth_action = {"action": "logout", "nonce": uuid.uuid4().hex}
        st.rerun()

# --- session state init ---
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- sidebar: title + health check ---
st.sidebar.title("MedRAG")

try:
    health_data = public_status("/health")
    dependencies = health_data.get("dependencies", {})
    all_ok = bool(dependencies) and all(status == "ok" for status in dependencies.values())
    if all_ok:
        st.sidebar.success("Backend: all systems ok")
    else:
        st.sidebar.warning("Backend: degraded")
        st.sidebar.json(health_data)
except requests.exceptions.RequestException:
    st.sidebar.error("Backend: unreachable")

st.sidebar.divider()

with st.sidebar.expander(f"Supported topics and sources ({len(TOPICS)} topics)"):
    st.markdown("**Curated sources:** [PubMed](https://pubmed.ncbi.nlm.nih.gov/), "
                "[OpenFDA drug labels](https://open.fda.gov/), "
                "[WHO guidelines](https://www.who.int/).")
    st.caption("Answers use retrieved evidence from these sources. PDFs you upload can also provide evidence in their own chat.")
    st.markdown("**Medical topics**")
    st.markdown("\n".join(f"- {topic_label(topic)}" for topic in TOPICS))
    st.caption("Coverage varies by topic and source. When the available evidence is insufficient, the assistant should say so.")


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


if st.sidebar.button("New Session"):
    try:
        resp = api_post(f"{API_URL}/sessions", json={}, timeout=10)
        resp.raise_for_status()
        new_session = resp.json()
        st.session_state.current_session_id = new_session["session_id"]
        st.session_state.selected_session_id = new_session["session_id"]
        st.session_state.messages = []
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
        st.session_state.selected_session_id = current if current in by_id else next(iter(by_id))
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
            st.rerun()
        except requests.exceptions.RequestException as e:
            st.sidebar.error(f"Session load failed: {e}")
else:
    if not st.session_state.get("sessions_load_failed"):
        st.sidebar.info("No sessions yet — create one above.")

st.sidebar.divider()

# --- sidebar: file uploader (session-scoped, per Phase 19 isolation design) ---
if st.session_state.current_session_id is not None:
    uploaded_file = st.sidebar.file_uploader(
        "Upload a PDF (this session only)", type=["pdf"],
        key=f"pdf_upload:{st.session_state.current_session_id}",
    )

    if uploaded_file is not None:
        # Rerun-model gotcha: uploaded_file stays non-None across every
        # subsequent rerun (e.g. when the user then sends a chat
        # message), so without this guard the SAME file would get
        # re-uploaded/re-indexed on every rerun. Keyed by session_id
        # too, so switching sessions and re-uploading the same file is
        # correctly treated as a new upload for that session.
        file_key = f"{st.session_state.current_session_id}:{uploaded_file.file_id}"
        if st.session_state.get("last_uploaded_key") != file_key:
            with st.sidebar.status("Uploading and indexing...", expanded=False):
                try:
                    files = {
                        "file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")
                    }
                    resp = api_post(
                        f"{API_URL}/sessions/{st.session_state.current_session_id}/documents",
                        files=files,
                        timeout=120,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    st.session_state.last_uploaded_key = file_key
                    st.sidebar.success(
                        f"Indexed {data['filename']} ({data['chunk_count']} chunks)"
                    )
                except requests.exceptions.RequestException as e:
                    st.sidebar.error(f"Upload failed: {e}")
else:
    st.sidebar.caption("Select or create a session to enable document upload.")

# --- main area ---
st.title("MedRAG — Medical Knowledge Assistant")
st.divider()

if st.session_state.current_session_id is None:
    st.info("Create or select a session to start chatting.")
else:
    # The callback runs before sidebar/history code can trigger a rerun. Keep
    # submissions outside the ephemeral chat widget event until processed.
    def capture_question():
        prompt = st.session_state.get("chat_prompt", "").strip()
        if prompt:
            sid = st.session_state.current_session_id
            st.session_state.pending_question = {"session_id": sid, "message": prompt}
            if not st.session_state.get("session_titles", {}).get(sid):
                st.session_state.setdefault("topic_titles", {}).setdefault(sid, title_from_query(prompt))

    def render_source_visuals(citations):
        tables_seen, images_seen = set(), set()
        for citation in citations:
            marker = f"[{citation['marker']}]"
            title = citation["title"]
            table = citation.get("table")
            if table and citation["chunk_id"] not in tables_seen:
                tables_seen.add(citation["chunk_id"])
                with st.expander(f"Source table {marker} — {title}", expanded=True):
                    if table.get("page_number") is not None:
                        st.caption(f"PDF page {table['page_number'] + 1}")
                    if table.get("part"):
                        st.caption(f"Table part {table['part']}")
                    rows = table["rows"]
                    width = max((len(row) for row in rows), default=0)
                    if width:
                        columns = {f"Column {i + 1}": [row[i] if i < len(row) else "" for row in rows]
                                   for i in range(width)}
                        st.dataframe(columns, hide_index=True)
                        st.caption("Extracted source cells; original header rows are retained. Check the source PDF for formatting.")
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
                with st.expander(f"Sources ({len(sources)})"):
                    for c in sources:
                        markers = ", ".join(f"[{marker}]" for marker in c["markers"])
                        source_name = {"user_upload": "Uploaded document", "who": "WHO", "pubmed": "PubMed", "openfda": "FDA label"}.get(c["source"], c["source"])
                        st.markdown(f"**{markers}** {c['title']} — *{source_name}*")
                        if c.get("url"):
                            st.markdown(f"[{c['url']}]({c['url']})")

    # chat input
    st.chat_input("Ask a medical question...", key="chat_prompt", on_submit=capture_question)
    pending = st.session_state.get("pending_question")
    if pending and pending["session_id"] == st.session_state.current_session_id:
        prompt = pending["message"]
        st.session_state.pop("pending_question", None)
        st.session_state.messages.append(
            {"role": "user", "content": prompt, "citations": None}
        )
        # State alone is rendered only on the next rerun. Draw this turn now,
        # before waiting for the backend, so the question is visible immediately.
        with st.chat_message("user"):
            st.write(prompt)
        with st.chat_message("assistant"), st.spinner("Thinking..."):
            try:
                resp = api_post(
                    f"{API_URL}/chat",
                    json={
                        "session_id": st.session_state.current_session_id,
                        "message": prompt,
                    },
                    timeout=60,
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
                        "content": f"Error contacting backend: {e}",
                        "citations": None,
                    }
                )
        st.rerun()
