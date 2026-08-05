import os
from pathlib import Path
from taskpanel.core.config import load_config, PanelConfig


def test_defaults(monkeypatch):
    for k in list(os.environ):
        if k.startswith("TASKPANEL_"):
            monkeypatch.delenv(k, raising=False)
    cfg = load_config()
    assert cfg.bind_host == "127.0.0.1"
    assert cfg.bind_port == 8470
    assert cfg.llm.max_tool_rounds == 20
    assert cfg.max_parallel is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("TASKPANEL_LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("TASKPANEL_LLM_MODEL", "deepseek-v4")
    monkeypatch.setenv("TASKPANEL_MAX_PARALLEL", "3")
    cfg = load_config()
    assert cfg.llm.base_url == "http://localhost:8000/v1"
    assert cfg.llm.model == "deepseek-v4"
    assert cfg.max_parallel == 3


def test_data_dir_expanded():
    cfg = load_config()
    assert str(cfg.data_dir).startswith(str(Path.home()))
