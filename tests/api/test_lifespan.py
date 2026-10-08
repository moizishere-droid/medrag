"""Tests for application startup and shutdown (the lifespan) and root discovery.

Every real service factory is replaced with a fake, so these run with no Docker.
They check the wiring (what ends up on app.state, in what order, and that
resources are released on shutdown), not the services themselves.
"""

import importlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

main = importlib.import_module("medrag.api.main")


class FakeQdrant:
    def __init__(self):
        self.collections_checked = False

    def get_collections(self):
        self.collections_checked = True
        return []


class FakeNeo4j:
    def __init__(self):
        self.verified = False
        self.closed = False

    def verify_connectivity(self):
        self.verified = True

    def close(self):
        self.closed = True


class FakePool:
    def __init__(self):
        self.closed = False

    def closeall(self):
        self.closed = True


@pytest.fixture
def startup(monkeypatch):
    """Replace every service factory the lifespan calls; record how each was used."""
    rec = SimpleNamespace(
        qdrant=FakeQdrant(),
        neo4j=FakeNeo4j(),
        pool=FakePool(),
        qdrant_urls=[],
        neo4j_args=[],
        pool_args=[],
        schema_pools=[],
        openai_keys=[],
        who_dirs=[],
        warmups=[],
    )

    def fake_qdrant(url):
        rec.qdrant_urls.append(url)
        return rec.qdrant

    def fake_driver(uri, auth):
        rec.neo4j_args.append((uri, auth))
        return rec.neo4j

    def fake_pool(host, port, dbname, user, password):
        rec.pool_args.append((host, port, dbname, user))
        return rec.pool

    def fake_openai(api_key, **kwargs):
        rec.openai_keys.append(api_key)
        return SimpleNamespace(api_key=api_key)

    def fake_who_lookup(who_dir):
        rec.who_dirs.append(who_dir)
        return {"diabetes": "https://who.int/d"}

    monkeypatch.setattr(main, "get_qdrant_client", fake_qdrant)
    monkeypatch.setattr(main, "GraphDatabase", SimpleNamespace(driver=fake_driver))
    monkeypatch.setattr(main, "get_postgres_pool", fake_pool)
    monkeypatch.setattr(main, "ensure_schema_via_pool", lambda pool: rec.schema_pools.append(pool))
    monkeypatch.setattr(main.openai, "OpenAI", fake_openai)
    monkeypatch.setattr(main, "build_who_source_url_lookup", fake_who_lookup)
    monkeypatch.setattr(main, "warmup_retrieval", lambda: rec.warmups.append(True))
    return rec


# --------------------------------------------------------------------------
# find_project_root
# --------------------------------------------------------------------------
def test_project_root_is_the_folder_that_contains_backend():
    root = main.find_project_root()
    assert (root / "backend").is_dir()
    assert main.PROJECT_ROOT == root


def test_missing_marker_raises_a_clear_error():
    with pytest.raises(RuntimeError, match="Could not find a 'no_such_folder_xyz' folder"):
        main.find_project_root("no_such_folder_xyz")


# --------------------------------------------------------------------------
# lifespan
# --------------------------------------------------------------------------
def test_startup_connects_every_service_and_exposes_it_on_app_state(startup):
    with TestClient(main.app):
        state = main.app.state
        assert state.qdrant_client is startup.qdrant and startup.qdrant.collections_checked
        assert state.neo4j_driver is startup.neo4j and startup.neo4j.verified
        assert state.pg_pool is startup.pool
        assert startup.schema_pools == [startup.pool]  # schema ensured on the pool
        assert state.openai_client.api_key == main.settings.openai_api_key
        assert state.who_source_urls == {"diabetes": "https://who.int/d"}
        assert startup.who_dirs == [str(main.PROJECT_ROOT / "data" / "raw" / "who")]
        assert startup.warmups == [True]


def test_local_warmup_can_be_disabled(startup, monkeypatch):
    monkeypatch.setattr(main.settings, "retrieval_warmup", False)
    with TestClient(main.app):
        assert startup.warmups == []


def test_shutdown_closes_the_neo4j_driver_and_every_pooled_connection(startup):
    with TestClient(main.app):
        assert not startup.neo4j.closed and not startup.pool.closed
    assert startup.neo4j.closed is True
    assert startup.pool.closed is True


def test_failed_schema_startup_releases_previously_opened_resources(startup, monkeypatch):
    def broken_schema(pool):
        raise RuntimeError("schema failed")
    monkeypatch.setattr(main, "ensure_schema_via_pool", broken_schema)
    with pytest.raises(RuntimeError, match="schema failed"):
        with TestClient(main.app):
            pass
    assert startup.neo4j.closed
    assert startup.pool.closed


def test_startup_fails_fast_when_qdrant_is_unreachable(startup):
    def unreachable():
        raise ConnectionError("qdrant down")

    startup.qdrant.get_collections = unreachable

    with pytest.raises(ConnectionError):
        with TestClient(main.app):
            pass

    assert startup.neo4j_args == []  # nothing after Qdrant was attempted
    assert startup.pool_args == []


def test_qdrant_url_falls_back_to_localhost_when_not_configured(startup, monkeypatch):
    monkeypatch.setattr(main.settings, "qdrant_url", None)
    with TestClient(main.app):
        pass
    monkeypatch.setattr(main.settings, "qdrant_url", "http://qdrant.internal:6333")
    with TestClient(main.app):
        pass
    assert startup.qdrant_urls == ["http://localhost:6333", "http://qdrant.internal:6333"]
