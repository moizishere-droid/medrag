import sys
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

with TestClient(app) as client:
    response = client.get("/sessions")
    print("Status:", response.status_code)
    print("Body:")
    import json
    print(json.dumps(response.json(), indent=2, default=str))