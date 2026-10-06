import sys
import os
from pathlib import Path

# find_project_root-anchored path setup, same as your other scripts
def find_project_root():
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "backend").exists():
            return parent
    raise RuntimeError("Could not find project root")

project_root = find_project_root()
sys.path.insert(0, str(project_root / "backend"))
sys.path.insert(0, str(project_root / "backend" / "src"))

from fastapi.testclient import TestClient
from medrag.api.main import app

def main():
    token = os.environ.get("MEDRAG_VERIFY_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with TestClient(app) as client:
        if client.get("/auth/config").json()["required"] and not token:
            raise RuntimeError("Set MEDRAG_VERIFY_TOKEN to an existing account token.")
        response = client.get("/sessions", headers=headers)
        response.raise_for_status()
        import json
        print(json.dumps(response.json(), indent=2, default=str))


if __name__ == "__main__":
    main()
