"""Shared pytest configuration and fixtures for the MedRAG test suite."""

import os
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# Must run before anything imports config.settings.
#
# config.settings builds a Settings() singleton at import time and hard-requires
# OPENAI_API_KEY and PUBMED_EMAIL. Environment variables outrank the .env file
# in pydantic-settings, so these placeholders:
#   1. let the suite import in CI, where no .env exists, and
#   2. guarantee unit tests never pick up your real key from .env.
# setdefault() respects a value already exported in the shell, which is how a
# `live` test run supplies a real key.
# ---------------------------------------------------------------------------
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder")
os.environ.setdefault("PUBMED_EMAIL", "test@example.com")

import pytest  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def make_points():
    """Factory for fake Qdrant hits. RRF and hybrid_search only read .payload."""

    def _make(*chunk_ids):
        return [
            SimpleNamespace(payload={"chunk_id": cid, "text": f"text of {cid}"})
            for cid in chunk_ids
        ]

    return _make