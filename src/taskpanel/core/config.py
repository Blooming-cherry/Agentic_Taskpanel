from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LLMConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    max_tool_rounds: int = 20
    timeout: float = 60.0
    max_retries: int = 3


@dataclass
class PanelConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    bind_host: str = "127.0.0.1"
    bind_port: int = 8470
    max_parallel: int | None = None
    worktree_auto_cleanup: bool = True
    max_retained_worktrees: int = 5
    ocr_timeout: int = 1800
    diff_context_lines: int = 8
    data_dir: Path = field(default_factory=lambda: Path("~/.taskpanel").expanduser())


def _env(key: str, default):
    return os.environ.get(key, default)


def load_config() -> PanelConfig:
    llm = LLMConfig(
        base_url=_env("TASKPANEL_LLM_BASE_URL", ""),
        api_key=_env("TASKPANEL_LLM_API_KEY", ""),
        model=_env("TASKPANEL_LLM_MODEL", ""),
        max_tool_rounds=int(_env("TASKPANEL_MAX_TOOL_ROUNDS", 20)),
        timeout=float(_env("TASKPANEL_LLM_TIMEOUT", 60.0)),
        max_retries=int(_env("TASKPANEL_MAX_RETRIES", 3)),
    )
    max_par = _env("TASKPANEL_MAX_PARALLEL", None)
    return PanelConfig(
        llm=llm,
        bind_host=_env("TASKPANEL_BIND_HOST", "127.0.0.1"),
        bind_port=int(_env("TASKPANEL_BIND_PORT", 8470)),
        max_parallel=int(max_par) if max_par else None,
        worktree_auto_cleanup=_env("TASKPANEL_WORKTREE_CLEANUP", "true").lower() == "true",
        max_retained_worktrees=int(_env("TASKPANEL_MAX_WORKTREES", 5)),
        ocr_timeout=int(_env("TASKPANEL_OCR_TIMEOUT", 1800)),
        diff_context_lines=int(_env("TASKPANEL_DIFF_CONTEXT", 8)),
        data_dir=Path(_env("TASKPANEL_DATA_DIR", "~/.taskpanel")).expanduser(),
    )
