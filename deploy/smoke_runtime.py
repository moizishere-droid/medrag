"""Check the actual packaged servers on the isolated CI network; no paid calls."""
import time

import requests


def main():
    deadline = time.monotonic() + 360
    while True:
        try:
            api = requests.get("http://api-ci:8000/health", timeout=5)
            api.raise_for_status()
            if api.json()["status"] != "ok":
                raise RuntimeError("Backend dependencies are unhealthy")
            config = requests.get("http://api-ci:8000/auth/config", timeout=5)
            config.raise_for_status()
            if config.json()["required"] is not True:
                raise RuntimeError("Packaged backend must require authentication")
            if requests.get("http://api-ci:8000/sessions", timeout=5).status_code != 401:
                raise RuntimeError("Packaged backend exposed unauthenticated sessions")
            ui = requests.get("http://ui-ci:8501/_stcore/health", timeout=5)
            ui.raise_for_status()
            print("Packaged backend and frontend healthy; private routes require authentication.")
            return
        except requests.RequestException as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError("Packaged servers did not become ready") from exc
            time.sleep(3)


if __name__ == "__main__":
    main()
