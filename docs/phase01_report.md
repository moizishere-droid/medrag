> Historical phase snapshot. See [the October 2026 audit](phase21_report.md#project-audit) for current corrections, verification, and limits.

# Phase 1: Environment Setup – Report

## Phase Objective

Establish a reproducible development environment, organize the project structure, and configure the foundation required for building the MedRAG system.

---

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

---

## Files Created

- `backend/requirements.txt`
- `backend/config/settings.py`
- `frontend/requirements.txt`
- `pyproject.toml`
- `install.bat`
- `.env.example`
- `.env`
- `.gitignore`
- `.python-version`
- `README.md`

---

## Results

- Successfully created a reproducible development environment.
- Backend and frontend dependencies installed without version conflicts.
- Centralized configuration system verified.
- Project package registered and importable from all modules.
- Development environment prepared for the data ingestion pipeline (Phase 2).

## Audit corrections — 6 October 2026

Installer referenced a deleted frontend requirements file and continued after failures. Fixed working-directory handling and failure checks. Sample database settings now match Compose. Removed unused incompatible experiment-tracking dependency.

Changed or reviewed files:

- [install.bat](../install.bat)
- [.env.example](../.env.example)
- [backend/requirements.txt](../backend/requirements.txt)
- [pyproject.toml](../pyproject.toml)

Verification: the original audit checks passed. Current results, subsequent fixes and the phase-by-phase review are recorded in [Phase 21](phase21_report.md) and the [current audit validation](phase21_report.md#project-audit-validation). Original observations above remain a historical phase snapshot; full notebook execution, paid API calls and source refreshes were not performed in this review.
