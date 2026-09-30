import streamlit as st
import requests

API_URL = "http://localhost:8000"

st.set_page_config(page_title="MedRAG", layout="wide")

# --- session state init ---
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- sidebar: title + health check ---
st.sidebar.title("MedRAG")

try:
    health_response = requests.get(f"{API_URL}/health", timeout=5)
    health_data = health_response.json()
    dependencies = health_data.get("dependencies", {})
    all_ok = all(status == "ok" for status in dependencies.values())
    if all_ok:
        st.sidebar.success("Backend: all systems ok")
    else:
        st.sidebar.warning("Backend: degraded")
        st.sidebar.json(health_data)
except requests.exceptions.RequestException:
    st.sidebar.error("Backend: unreachable")

st.sidebar.divider()


# --- sidebar: session switcher + new session ---
def load_sessions():
    try:
        resp = requests.get(f"{API_URL}/sessions", timeout=5)
        resp.raise_for_status()
        return resp.json().get("sessions", [])
    except requests.exceptions.RequestException as e:
        st.sidebar.error(f"Session load failed: {e}")
        return []


def session_label(s):
    if s.get("title"):
        return s["title"]
    return f"Session ({s['created_at'][:16]}) - {s['session_id'][:8]}"


if st.sidebar.button("New Session"):
    resp = requests.post(f"{API_URL}/sessions", json={})
    new_session = resp.json()
    st.session_state.current_session_id = new_session["session_id"]
    st.session_state.messages = []
    st.rerun()

sessions = load_sessions()
if sessions:
    # Select on the session dict itself (via format_func), not on a
    # plain label string - two sessions can share an identical label
    # (same null-title fallback timestamp, or literally the same
    # title), and resolving a selection back via labels.index(...)
    # silently picks the FIRST matching one: a real correctness bug
    # (wrong session loads) and the likely cause of an earlier
    # intermittent Streamlit frontend crash caused by duplicate
    # selectbox option labels confusing its internal state diffing.
    current_index = next(
        (i for i, s in enumerate(sessions) if s["session_id"] == st.session_state.current_session_id),
        0,
    )
    selected_session = st.sidebar.selectbox(
        "Session",
        sessions,
        index=current_index,
        format_func=session_label,
    )
    selected_id = selected_session["session_id"]

    if selected_id != st.session_state.current_session_id:
        st.session_state.current_session_id = selected_id
        history_resp = requests.get(f"{API_URL}/sessions/{selected_id}", timeout=5)
        st.session_state.messages = history_resp.json().get("messages", [])
        st.rerun()
else:
    st.sidebar.info("No sessions yet — create one above.")

st.sidebar.divider()

# --- sidebar: file uploader (session-scoped, per Phase 19 isolation design) ---
if st.session_state.current_session_id is not None:
    uploaded_file = st.sidebar.file_uploader(
        "Upload a PDF (this session only)", type=["pdf"]
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
                    resp = requests.post(
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
    # render existing messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("citations"):
                with st.expander(f"Sources ({len(msg['citations'])})"):
                    for c in msg["citations"]:
                        st.markdown(f"**[{c['marker']}]** {c['title']} — *{c['source']}*")
                        if c.get("url"):
                            st.markdown(f"[{c['url']}]({c['url']})")

    # chat input
    if prompt := st.chat_input("Ask a medical question..."):
        st.session_state.messages.append(
            {"role": "user", "content": prompt, "citations": None}
        )
        with st.spinner("Thinking..."):
            try:
                resp = requests.post(
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