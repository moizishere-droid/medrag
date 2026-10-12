"""Supervise the API, UI and same-origin proxy inside one Modal container."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError
from modal_config import validate_modal_environment


def wait_for_service(url, children, timeout=240):
    """Keep the public port closed until a service reports HTTP readiness."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(child.poll() is not None for child in children):
            raise RuntimeError("A service exited during startup; inspect its preceding logs")
        try:
            with urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Service readiness timed out; inspect startup logs")


STARTUP_DIR = Path("/tmp/medrag-startup")


def publish_status(message, ready=False):
    STARTUP_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STARTUP_DIR / "status.tmp"
    temporary.write_text(json.dumps({"ready": ready, "message": message}), encoding="utf-8")
    temporary.replace(STARTUP_DIR / "status.json")


def start_services(commands, children):
    STARTUP_DIR.mkdir(parents=True, exist_ok=True)
    (STARTUP_DIR / "ready").unlink(missing_ok=True)
    publish_status("Connecting databases and warming the retrieval models...")
    # Serve a lightweight loading page while API/model initialization runs.
    children.append(subprocess.Popen(commands[2]))
    children.append(subprocess.Popen(commands[0]))
    wait_for_service("http://127.0.0.1:8000/health", children)
    publish_status("Knowledge sources are ready. Opening your chat...")
    children.append(subprocess.Popen(commands[1]))
    wait_for_service("http://127.0.0.1:8501/_stcore/health", children, timeout=30)
    (STARTUP_DIR / "ready").touch()
    publish_status("Ready", ready=True)
    print("API and frontend ready; chat enabled", flush=True)


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
        start_services(commands, children)
        # Persist downloaded weights and ONNX exports for later cold starts.
        try:
            import modal
            modal.Volume.from_name("medrag-model-cache").commit()
            print("Model cache saved for subsequent starts", flush=True)
        except Exception as exc:
            print("Model cache save failed: " + type(exc).__name__, flush=True)
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
