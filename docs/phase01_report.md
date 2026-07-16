# Phase 1: Environment Setup — Report

## What Was Built

- **`backend/requirements.txt`** — pinned, version-compatible dependencies for the backend: LLM/embeddings (openai), vector DB (qdrant-client), graph DB (neo4j), relational DB (sqlalchemy, psycopg2-binary), config loading (pydantic-settings, python-dotenv), medical NER (spacy, scispacy), image embeddings (torch, open-clip-torch, pillow), sparse retrieval (rank-bm25), reranking (sentence-transformers, transformers), API (fastapi, uvicorn), ingestion (requests, biopython, pypdf), evaluation (ragas), tracking (wandb), testing (pytest).
- **`frontend/requirements.txt`** — lightweight dependencies for the Streamlit UI: streamlit, requests, python-dotenv, pillow.
- **`pyproject.toml`** — simplified to hold no duplicate dependency list; its only job now is making `medrag` an installable/importable package (`backend/src` mapped as the package root).
- **`install.bat`** — updated to create a single `venv`, install both requirements files, then register the `medrag` package with `pip install -e . --no-deps`.
- Package registered and verified: `import torch, spacy, fastapi, openai, qdrant_client, neo4j, streamlit` all succeed with no errors.

## Key Decisions & Reasoning

1. **One shared `venv` instead of separate backend/frontend environments** — simpler to manage for a single-developer portfolio project; the two requirements files still keep the dependency lists cleanly separated by concern.
2. **Dependencies moved from `pyproject.toml` into `requirements.txt` files, pinned to exact versions** (not ranges) — chosen for reproducibility and to make future version conflicts easier to diagnose (a fixed, known-good snapshot rather than a moving target).
3. **`pyproject.toml` kept, but stripped of dependencies** — still needed so `medrag` can be `pip install -e .`'d and imported as `medrag.x.y` throughout the codebase, without duplicating the dependency list already in `requirements.txt`.
4. **Skipped the notebook for this phase** — Phase 1 is mechanical setup (installing packages, verifying imports), not a concept to learn hands-on, so notebook-first didn't apply here (same exception made for Phase 0).
5. **Deferred Docker services (Qdrant, Neo4j, Postgres) setup** — none of the three databases are needed until later phases (Qdrant: Phase 9, Neo4j: Phase 14, Postgres: Phase 17), so ingestion work (Phase 2) can start immediately without blocking on Docker installation.

## Results

- Backend and frontend dependencies installed cleanly into a single `venv` with no version conflicts.
- `medrag` package installed in editable mode and importable project-wide.
- All core library imports verified working.

## Challenges & Solutions

- **Initial confusion between `pyproject.toml` dependencies and `requirements.txt`** — resolved by clearly separating responsibilities: `requirements.txt` files own dependency installation, `pyproject.toml` only owns package structure/import registration.
- **Python version compatibility** — `requires-python` constraint widened to `>=3.10,<3.13` to support common current Python versions without breaking pinned library compatibility (notably spacy/scispacy/torch/numpy).