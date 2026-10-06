"""Runner failures must be visible to future CI/jobs without corrupting data."""
import importlib
import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests


@pytest.fixture
def scripts(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "backend" / "scripts"
    monkeypatch.syspath_prepend(str(path))
    return path


def test_openfda_failed_refresh_never_overwrites_and_exits_unsuccessfully(scripts, monkeypatch):
    runner = importlib.import_module("run_openfda_ingestion")
    save = Mock()
    monkeypatch.setattr(runner, "TOPICS", ["diabetes"])
    monkeypatch.setattr(runner, "fetch_drugs_for_topic", Mock(side_effect=requests.ConnectionError("offline")))
    monkeypatch.setattr(runner, "save_drugs", save)
    with pytest.raises(RuntimeError, match="refresh incomplete"):
        runner.main()
    save.assert_not_called()


def test_who_failed_refresh_never_overwrites_and_exits_unsuccessfully(scripts, monkeypatch):
    runner = importlib.import_module("run_who_ingestion")
    save = Mock()
    monkeypatch.setattr(runner, "TOPIC_DOCS", {"diabetes": ("https://example.org/doc.pdf", "Guide")})
    monkeypatch.setattr(runner, "fetch_who_guideline", Mock(side_effect=requests.ConnectionError("offline")))
    monkeypatch.setattr(runner, "save_guideline", save)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="refresh incomplete"):
        runner.main()
    save.assert_not_called()


@pytest.mark.parametrize("filename", ["verify_phase19.py", "verify_sessions_list.py"])
def test_manual_verification_script_imports_without_live_work(scripts, monkeypatch, filename):
    client = Mock(side_effect=AssertionError("Import must not start live verification"))
    monkeypatch.setattr("fastapi.testclient.TestClient", client)
    namespace = runpy.run_path(str(scripts / filename), run_name="offline_import_check")
    assert callable(namespace["main"])
    client.assert_not_called()


def test_all_production_modules_and_runners_import_offline(scripts):
    import pkgutil
    import medrag
    for module in pkgutil.walk_packages(medrag.__path__, prefix="medrag."):
        importlib.import_module(module.name)
    for path in sorted(scripts.glob("*.py")):
        # Run under a non-main name: import guards must keep ingestion,
        # database startup and paid evaluation out of this smoke check.
        runpy.run_path(str(path), run_name="offline_import_check")
