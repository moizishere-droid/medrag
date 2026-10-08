"""Modal entry point: same-origin app; separate persistent cloud databases."""
import subprocess
import sys
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
app = modal.App("medrag-portfolio")
secret = modal.Secret.from_name("medrag-demo")
cache = modal.Volume.from_name("medrag-model-cache", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("build-essential", "caddy")
    .run_commands("pip install torch==2.14.1+cpu --index-url https://download.pytorch.org/whl/cpu")
    .pip_install_from_requirements(str(ROOT / "backend/requirements-runtime.txt"))
    .pip_install_from_requirements(str(ROOT / "frontend/requirements.txt"))
    .env({"PYTHONPATH": "/app/backend:/app/backend/src:/app/deploy", "HF_HOME": "/cache/huggingface",
          "FASTEMBED_CACHE_PATH": "/cache/fastembed", "RERANK_BACKEND": "onnx", "RERANK_THREADS": "2",
          "RETRIEVAL_WARMUP": "true", "PYTHONUNBUFFERED": "1"})
    .add_local_dir(ROOT / "backend", "/app/backend", copy=True, ignore=["**/__pycache__/**", "**/*.pyc", "**/*.env", "**/.env*"])
    .add_local_dir(ROOT / "frontend", "/app/frontend", copy=True, ignore=["**/__pycache__/**", "**/*.pyc"])
    .add_local_file(ROOT / "pyproject.toml", "/app/pyproject.toml", copy=True)
    .add_local_dir(ROOT / "data/images/who", "/app/data/images/who", copy=True)
    .add_local_dir(ROOT / "data/tables/who", "/app/data/tables/who", copy=True)
    .add_local_dir(ROOT / "data/raw/who", "/app/data/raw/who", copy=True, ignore=["*.pdf"])
)
for filename in ("modal_config.py", "modal_server.py", "Caddyfile.modal", "check_readiness.py"):
    image = image.add_local_file(ROOT / "deploy" / filename, "/app/deploy/" + filename, copy=True)
image = image.workdir("/app").run_commands("pip install --no-deps .", "pip check", "ln -s /cache/exports /app/.medrag_cache")


@app.function(image=image, secrets=[secret], volumes={"/cache": cache}, cpu=1, memory=4096,
              min_containers=0, max_containers=1, scaledown_window=60, timeout=600)
@modal.concurrent(max_inputs=20)
@modal.web_server(8080, startup_timeout=180, label="medrag")
def web():
    subprocess.Popen([sys.executable, "deploy/modal_server.py"])


provision_image = image.add_local_dir(ROOT / "data/processed", "/app/data/processed", copy=False)


@app.function(image=provision_image, secrets=[secret], volumes={"/cache": cache}, cpu=1, memory=4096,
              min_containers=0, max_containers=1, timeout=1800)
def provision():
    """Explicit account-owner action. Upsert curated data, never reset collections."""
    import os
    from modal_config import validate_modal_environment
    validate_modal_environment(os.environ)
    for script in ("run_qdrant_ingestion.py", "run_graph_ingestion.py"):
        subprocess.run([sys.executable, "backend/scripts/" + script], check=True)
    subprocess.run([sys.executable, "deploy/check_readiness.py"], check=True,
                   env={**os.environ, "AUTH_REQUIRED": "true", "AUTH_COOKIE_SECURE": "true"})
    cache.commit()
