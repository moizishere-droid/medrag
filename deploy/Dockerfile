# Build from the repository root. CPU PyTorch avoids shipping CUDA libraries.
FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS backend-base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/backend:/app/backend/src HF_HOME=/app/.cache/huggingface
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements-runtime.txt /app/backend/requirements-runtime.txt
RUN pip install --no-cache-dir torch==2.14.1+cpu --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir pip==26.2.1 setuptools==83.0.0 wheel==0.46.3 \
    && pip install --no-cache-dir -r backend/requirements-runtime.txt \
    && pip check
ENV FASTEMBED_CACHE_PATH=/app/.medrag_cache/fastembed
COPY pyproject.toml .
COPY backend /app/backend
COPY deploy/check_readiness.py /app/deploy/check_readiness.py
COPY data/raw/who /app/data/raw/who
COPY data/tables/who /app/data/tables/who
COPY data/images/who /app/data/images/who
RUN pip install --no-deps . \
    && useradd --uid 10001 --create-home medrag \
    && mkdir -p /app/.cache/huggingface /app/.medrag_cache \
    && chown -R medrag:medrag /app/.cache /app/.medrag_cache

FROM backend-base AS test
COPY backend/requirements-experiments.txt /app/backend/requirements-experiments.txt
RUN pip install --no-cache-dir torchvision==0.29.1+cpu --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r backend/requirements-experiments.txt && pip check
ENV PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest-cache"
COPY frontend /app/frontend
COPY tests /app/tests
COPY deploy /app/deploy
USER medrag
CMD ["python", "-m", "pytest", "-q"]

FROM backend-base AS backend
USER medrag
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "medrag.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS frontend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/backend/src
WORKDIR /app
COPY frontend/requirements.txt /app/frontend/requirements.txt
RUN pip install --no-cache-dir -r frontend/requirements.txt && pip check \
    && useradd --uid 10001 --create-home medrag
RUN pip install --no-cache-dir pip==26.2.1 setuptools==83.0.0 wheel==0.46.3 && pip check
COPY backend/src /app/backend/src
COPY frontend /app/frontend
USER medrag
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"
CMD ["streamlit", "run", "frontend/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
