"""Supervise the API, UI and same-origin proxy inside one Modal container."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from modal_config import validate_modal_environment


def main():
    origin = validate_modal_environment(os.environ)
    if os.environ.get("MEDRAG_DEMO_READY") != "true":
        raise RuntimeError("The hosted corpus must be provisioned before enabling the demo")
    Path("/cache/exports").mkdir(parents=True, exist_ok=True)
    os.environ.update(AUTH_REQUIRED="true", AUTH_COOKIE_SECURE="true", CORS_ORIGINS=json.dumps([origin]),
                      MEDRAG_API_URL="http://127.0.0.1:8000", MEDRAG_BROWSER_API_URL=origin + "/api")
    commands = [
        [sys.executable, "-m", "uvicorn", "medrag.api.main:app", "--host", "127.0.0.1", "--port", "8000", "--root-path", "/api", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"],
        [sys.executable, "-m", "streamlit", "run", "frontend/streamlit_app.py", "--server.address=127.0.0.1", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"],
        ["caddy", "run", "--config", "deploy/Caddyfile.modal"],
    ]
    children = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command))
        while True:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A demo service stopped; restarting the container is required")
            time.sleep(1)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()


if __name__ == "__main__":
    main()
