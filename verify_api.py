import sys, os
from pathlib import Path

def find_project_root(marker="backend", start=None):
    current = Path(start or os.getcwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / marker).is_dir():
            return candidate
    raise RuntimeError(f"Could not find a {marker} folder above {current}")

PROJECT_ROOT = find_project_root()
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from fastapi.testclient import TestClient
from medrag.api.main import app

with TestClient(app) as client:
    created = client.post("/sessions", json={"title": "Chat test"})
    session_id = created.json()["session_id"]
    print("SESSION:", session_id)

    chat1 = client.post("/chat", json={"session_id": session_id, "message": "What does metformin treat?"})
    print("CHAT 1:", chat1.status_code)
    print(chat1.json())

    chat2 = client.post("/chat", json={"session_id": session_id, "message": "What are its contraindications?"})
    print("\nCHAT 2 (follow-up):", chat2.status_code)
    print(chat2.json())

    history = client.get(f"/sessions/{session_id}")
    print("\nFULL HISTORY:", len(history.json()["messages"]), "messages")
