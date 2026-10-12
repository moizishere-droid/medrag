"""Hosted startup must withhold the public listener until both services are ready."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock
import pytest

spec = importlib.util.spec_from_file_location("modal_server_test", Path(__file__).resolve().parents[2] / "deploy/modal_server.py")
module = importlib.util.module_from_spec(spec)
config_spec = importlib.util.spec_from_file_location("modal_config", Path(__file__).resolve().parents[2] / "deploy/modal_config.py")
config = importlib.util.module_from_spec(config_spec)
config_spec.loader.exec_module(config)
sys.modules.setdefault("modal_config", config)
spec.loader.exec_module(module)


def test_loading_proxy_then_api_then_ui(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "STARTUP_DIR", tmp_path)
    events = []
    def spawn(command):
        events.append(command)
        return Mock()
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    monkeypatch.setattr(module, "wait_for_service", lambda url, children, **kwargs: events.append(url))
    children = []
    module.start_services(["api", "ui", "proxy"], children)
    assert events == ["proxy", "api", "http://127.0.0.1:8000/health", "ui", "http://127.0.0.1:8501/_stcore/health"]
    assert (tmp_path / "ready").exists()
    assert len(children) == 3


def test_failed_api_keeps_chat_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "STARTUP_DIR", tmp_path)
    spawn = Mock()
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    monkeypatch.setattr(module, "wait_for_service", Mock(side_effect=RuntimeError("not ready")))
    with pytest.raises(RuntimeError):
        module.start_services(["api", "ui", "proxy"], [])
    assert [call.args[0] for call in spawn.call_args_list] == ["proxy", "api"]
    assert not (tmp_path / "ready").exists()


def test_readiness_stops_when_child_exits():
    with pytest.raises(RuntimeError, match="exited"):
        module.wait_for_service("http://unused", [Mock(poll=Mock(return_value=1))])
