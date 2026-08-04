# TaskPanel Web 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个本地 Web 任务面板,并行运行多个上下文互相隔离的 AI agent 任务(普通问答 + OCR 代码审查),复刻 Codex 桌面端三栏体验。

**Architecture:** 三层 —— `core`(LLMClient 双实现+能力探测、AgentLoop 每任务独立消息历史、Task 状态机、工具、OCR 子进程包装)、`store`(JSONL 消息/事件 + meta 持久化、worktree 隔离)、`web`(FastAPI + WebSocket + React/Vite 三栏前端)。后端经 Anthropic 兼容端点连 DeepSeek 映射;模型不支持 tool_use 时自动降级纯文本。

**Tech Stack:** Python 3.11+ (uv), FastAPI + uvicorn + websockets, httpx, anthropic SDK(可选), React 18 + Vite, `@alibaba-group/open-code-review`(`ocr` CLI), pytest, git ≥ 2.41。

## Global Constraints

- Python ≥ 3.11;依赖经 uv 管理;测试运行命令 `uv run pytest`。
- 所有任务数据落盘在 `~/.taskpanel/tasks/<id>/`:`messages.jsonl`、`events.jsonl`(每条带自增 `seq`)、`meta.json`。
- 消息采用 Anthropic Messages API 格式(`role`/`content`,含 `text`、`tool_use`、`tool_result` 块)。
- 后端只绑定 `127.0.0.1`;启动生成 `~/.taskpanel/.auth_token`(0600);所有 REST 带 `X-Auth-Token` 头、WS 用 `?token=`;不开启跨源 CORS。
- 事件 schema:`{"seq": int, "task_id": str, "type": str, ...}`,类型 ∈ `text_delta`/`tool_use`/`tool_result`/`status`/`error`。
- 任务类型 `kind` ∈ `project`|`chat`;`project` 才有文件/脚本/OCR 工具与可选 worktree 隔离。
- OCR 环境变量:`OCR_LLM_URL`、`OCR_LLM_TOKEN`、`OCR_LLM_MODEL`、`OCR_USE_ANTHROPIC=true`;超时默认 30 分钟。
- 提交信息用中文,格式 `feat: ...` / `test: ...` / `fix: ...`。
- 每个任务末尾: 测试全绿 + git commit。

---

### Task 1: 项目脚手架

**Files:**
- Create: `taskpanel/pyproject.toml`
- Create: `taskpanel/.gitignore`
- Create: `taskpanel/src/taskpanel/__init__.py`
- Create: `taskpanel/src/taskpanel/core/__init__.py`
- Create: `taskpanel/src/taskpanel/store/__init__.py`
- Create: `taskpanel/src/taskpanel/web/__init__.py`
- Create: `taskpanel/tests/__init__.py`

**Interfaces:**
- Produces: 可 `import taskpanel` 的 src 布局包 + pytest 可用。

- [ ] **Step 1: 初始化 uv 项目**

在 `C:\Users\admin\projects\taskpanel` 下运行:
```bash
uv init --name taskpanel --python 3.11
uv add fastapi uvicorn[standard] websockets httpx pydantic
uv add --dev pytest pytest-asyncio
```
若 `uv init` 已生成 `pyproject.toml`/`main.py`,按 Step 2 覆盖 `pyproject.toml` 并删除 `main.py`。

- [ ] **Step 2: 写 `pyproject.toml`**

```toml
[project]
name = "taskpanel"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["fastapi>=0.110", "uvicorn[standard]>=0.29", "websockets>=12", "httpx>=0.27", "pydantic>=2.6"]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "anthropic>=0.34"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.uv]
package = true
```

- [ ] **Step 3: 写 `.gitignore`**

```gitignore
__pycache__/
*.pyc
.venv/
dist/
node_modules/
frontend/dist/
web/static/
.pytest_cache/
.taskpanel/
```

- [ ] **Step 4: 创建包骨架**

```bash
mkdir -p src/taskpanel/core src/taskpanel/store src/taskpanel/web tests
touch src/taskpanel/__init__.py src/taskpanel/core/__init__.py src/taskpanel/store/__init__.py src/taskpanel/web/__init__.py tests/__init__.py
```

- [ ] **Step 5: 验证**

```bash
uv run python -c "import taskpanel; print('ok')"
uv run pytest -q
```
Expected: 打印 `ok`,pytest 无测试通过(exit 0)。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: uv 项目脚手架(src 布局 + pytest)"
```

---

### Task 2: 配置模块 `core/config.py`

**Files:**
- Create: `taskpanel/src/taskpanel/core/config.py`
- Test: `taskpanel/tests/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass class LLMConfig: base_url, api_key, model, max_tool_rounds=20, timeout=60.0, max_retries=3`
  - `@dataclass class PanelConfig: llm: LLMConfig, bind_host="127.0.0.1", bind_port=8470, max_parallel=None, worktree_auto_cleanup=True, max_retained_worktrees=5, ocr_timeout=1800, diff_context_lines=8, data_dir="~/.taskpanel"`
  - `def load_config() -> PanelConfig` — 读环境变量(`TASKPANEL_LLM_BASE_URL`、`TASKPANEL_LLM_API_KEY`、`TASKPANEL_LLM_MODEL`、`TASKPANEL_MAX_PARALLEL`、`TASKPANEL_BIND_PORT` 等),缺省用默认值;`data_dir` 用 `Path.expanduser()`。

- [ ] **Step 1: 写失败测试**

`tests/test_config.py`:
```python
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
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL(ImportError / AttributeError)

- [ ] **Step 3: 实现**

`src/taskpanel/core/config.py`:
```python
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
```

- [ ] **Step 4: 运行验证通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS(3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/taskpanel/core/config.py tests/test_config.py
git commit -m "feat: core 配置模块(env 覆盖 + 默认值)"
```

---

### Task 3: 任务模型 `core/task.py`

**Files:**
- Create: `taskpanel/src/taskpanel/core/task.py`
- Test: `taskpanel/tests/test_task.py`

**Interfaces:**
- Produces:
  - `class TaskState(str, Enum)` ∈ `QUEUED/RUNNING/PAUSED/DONE/ERROR/STOPPED`(值为小写字符串)。
  - `@dataclass class Task: id, kind, prompt, cwd, use_worktree, title, status, messages, token_count, created_at, updated_at, error=None, worktree=None, keep_worktree=False`
  - `def make_task(kind, prompt, cwd=None, use_worktree=False) -> Task`(自动 `uuid4().hex[:8]` 为 id,`created_at/updated_at` 用 `datetime.now(timezone.utc).isoformat()`,状态 `QUEUED`,标题=prompt 前 30 字)。

- [ ] **Step 1: 写失败测试**

`tests/test_task.py`:
```python
from taskpanel.core.task import Task, TaskState, make_task


def test_make_task_fields():
    t = make_task("chat", "帮我整理这个问题的要点，稍微长一点的标题", cwd=None)
    assert t.kind == "chat"
    assert t.status == TaskState.QUEUED
    assert t.title == "帮我整理这个问题的要点，稍微长一点"
    assert len(t.id) == 8
    assert t.messages == []


def test_state_values():
    assert TaskState.RUNNING.value == "running"
    assert TaskState.PAUSED.value == "paused"
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_task.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/taskpanel/core/task.py`:
```python
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class Task:
    id: str
    kind: str
    prompt: str
    cwd: str | None
    use_worktree: bool
    title: str
    status: TaskState
    messages: list[dict] = field(default_factory=list)
    token_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    error: str | None = None
    worktree: str | None = None
    keep_worktree: bool = False

    def touch(self):
        self.updated_at = datetime.now(timezone.utc).isoformat()


def make_task(kind: str, prompt: str, cwd: str | None = None,
              use_worktree: bool = False) -> Task:
    now = datetime.now(timezone.utc).isoformat()
    return Task(
        id=uuid.uuid4().hex[:8],
        kind=kind,
        prompt=prompt,
        cwd=cwd,
        use_worktree=use_worktree,
        title=prompt[:30],
        status=TaskState.QUEUED,
        created_at=now,
        updated_at=now,
    )
```

- [ ] **Step 4: 运行验证通过**

Run: `uv run pytest tests/test_task.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/taskpanel/core/task.py tests/test_task.py
git commit -m "feat: Task 模型与状态机"
```

---

### Task 4: LLMClient 抽象 + AnthropicSDKClient + 能力探测

**Files:**
- Create: `taskpanel/src/taskpanel/core/llm.py`
- Test: `taskpanel/tests/test_llm.py`

**Interfaces:**
- Consumes: `core.config.LLMConfig`
- Produces:
  - `@dataclass class LLMEvent: type, text="", tool_use=None, error="", raw=None`(type ∈ `text_delta`/`tool_use`/`done`/`error`)
  - `class LLMClient(ABC)`: `async def stream(self, messages: list[dict], tools: list[dict] | None) -> AsyncIterator[LLMEvent]`;`async def probe(self) -> bool`
  - `class AnthropicSDKClient(LLMClient)` 用 `anthropic.AsyncAnthropic(base_url=cfg.base_url, api_key=cfg.api_key)`,流式 `client.messages.stream(model, max_tokens, messages, tools)`;`tool_use` 事件累计成块后作为一个 `LLMEvent(type="tool_use", tool_use={...})` 发出。
  - `def build_client(cfg: LLMConfig) -> LLMClient` — 有 `anthropic` 依赖则返回 `AnthropicSDKClient`,否则返回 `RawHTTPClient`(Task 5)。

- [ ] **Step 1: 写失败测试**

`tests/test_llm.py`:
```python
import pytest
from taskpanel.core.config import LLMConfig
from taskpanel.core.llm import build_client, AnthropicSDKClient, LLMClient


def test_build_client_prefers_sdk(monkeypatch):
    monkeypatch.setattr("taskpanel.core.llm.HAS_ANTHROPIC", True)
    cfg = LLMConfig(base_url="http://localhost:9999/v1", api_key="k", model="m")
    client = build_client(cfg)
    assert isinstance(client, AnthropicSDKClient)


@pytest.mark.asyncio
async def test_probe_detects_no_tool_support():
    """用假 client 模拟探测返回 False 的路径由 build_client 之上的逻辑处理;
    此处验证 probe 接口存在且能跑(空工具列表返回 True)。"""
    class FakeClient(LLMClient):
        def __init__(self):
            self.called = False
        async def stream(self, messages, tools=None):
            self.called = True
            yield __import__("taskpanel.core.llm", fromlist=["LLMEvent"]).LLMEvent(type="done")
        async def probe(self):
            return True

    c = FakeClient()
    assert await c.probe() is True
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_llm.py -v`
Expected: FAIL(ImportError)

- [ ] **Step 3: 实现**

`src/taskpanel/core/llm.py`:
```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Any

try:  # pragma: no cover
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from taskpanel.core.config import LLMConfig


@dataclass
class LLMEvent:
    type: str
    text: str = ""
    tool_use: dict | None = None
    error: str = ""
    raw: Any = None


class LLMClient(ABC):
    @abstractmethod
    async def stream(self, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[LLMEvent]:
        ...

    @abstractmethod
    async def probe(self) -> bool:
        """向模型发一条带工具定义的测试消息,返回是否支持 tool_use。"""


class AnthropicSDKClient(LLMClient):
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._client = anthropic.AsyncAnthropic(
            base_url=cfg.base_url or None, api_key=cfg.api_key or "unused"
        )

    async def stream(self, messages, tools=None):
        kwargs = dict(
            model=self.cfg.model, max_tokens=4096, messages=messages,
            stream=True, timeout=self.cfg.timeout,
        )
        if tools:
            kwargs["tools"] = tools
        async with self._client.messages.stream(**kwargs) as s:
            block = None  # 累积 text/tool_use
            async for text in s.text_stream:
                yield LLMEvent(type="text_delta", text=text)
            msg = await s.get_final_message()
        for b in msg.content:
            if b.type == "tool_use":
                yield LLMEvent(type="tool_use", tool_use={
                    "id": b.id, "name": b.name, "input": b.input})
        yield LLMEvent(type="done")

    async def probe(self) -> bool:
        resp = await self._client.messages.create(
            model=self.cfg.model,
            max_tokens=16,
            messages=[{"role": "user",
                       "content": "用 force_tool 工具回答 one"}],
            tools=[{"name": "force_tool",
                    "description": "always call",
                    "input_schema": {"type": "object",
                                     "properties": {"x": {"type": "string"}},
                                     "required": ["x"]}}],
        )
        return any(getattr(b, "type", "") == "tool_use" for b in resp.content)


def build_client(cfg: LLMConfig) -> LLMClient:
    if HAS_ANTHROPIC:
        return AnthropicSDKClient(cfg)
    from taskpanel.core.llm_raw import RawHTTPClient
    return RawHTTPClient(cfg)
```

- [ ] **Step 4: 运行验证通过**

Run: `uv run pytest tests/test_llm.py -v`
Expected: PASS(anthropic 已在 dev 依赖,`build_client` 走 SDK 分支)

- [ ] **Step 5: Commit**

```bash
git add src/taskpanel/core/llm.py tests/test_llm.py
git commit -m "feat: LLMClient 抽象 + AnthropicSDKClient + probe"
```

---

### Task 5: RawHTTPClient 兜底实现 + 客户端选择

**Files:**
- Create: `taskpanel/src/taskpanel/core/llm_raw.py`
- Test: `taskpanel/tests/test_llm_raw.py`

**Interfaces:**
- Consumes: `core.config.LLMConfig`、`core.llm.LLMClient/LLMEvent`
- Produces:
  - `class RawHTTPClient(LLMClient)` — `httpx.AsyncClient` POST `{base_url}/v1/messages`,SSE 流解析 `content_block_delta`(text)、`message_delta`;结束后聚合 `content` 块,发出 `tool_use` 事件。`probe()` 发带工具定义的最小请求。
  - 暴露 `def pick_client(cfg) -> tuple[LLMClient, str]`,返回 (client, "anthropic"|"raw"),SDK 首次运行时协议错则回退 raw。

- [ ] **Step 1: 写失败测试**

`tests/test_llm_raw.py`:
```python
import json
import httpx
import pytest
from taskpanel.core.config import LLMConfig
from taskpanel.core.llm_raw import RawHTTPClient


@pytest.mark.asyncio
async def test_raw_stream_parses_text_and_tool_use(monkeypatch):
    def fake_post(*a, **kw):
        class R:
            status_code = 200
            async def aiter_lines(self):
                payload = {
                    "content": [
                        {"type": "text", "text": "hi"},
                        {"type": "tool_use", "id": "t1", "name": "bash",
                         "input": {"cmd": "pwd"}},
                    ],
                    "stop_reason": "tool_use",
                }
                for line in json.dumps(payload).splitlines():
                    yield line
        return R()
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = RawHTTPClient(LLMConfig(base_url="http://x/v1", api_key="k", model="m"))
    events = [e async for e in client.stream([{"role": "user", "content": "hi"}], [])]
    texts = [e.text for e in events if e.type == "text_delta"]
    tools = [e.tool_use for e in events if e.type == "tool_use"]
    assert texts == ["hi"]
    assert tools[0]["name"] == "bash"
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_llm_raw.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/taskpanel/core/llm_raw.py`:
```python
from __future__ import annotations
import json
import httpx

from taskpanel.core.config import LLMConfig
from taskpanel.core.llm import LLMClient, LLMEvent


class RawHTTPClient(LLMClient):
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._http = httpx.AsyncClient(timeout=cfg.timeout)

    def _url(self) -> str:
        base = self.cfg.base_url.rstrip("/")
        return base + "/v1/messages" if not base.endswith("/messages") else base

    async def stream(self, messages, tools=None):
        body = {"model": self.cfg.model, "max_tokens": 4096, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self._http.post(self._url(), json=body,
                                     headers={"x-api-key": self.cfg.api_key,
                                              "anthropic-version": "2023-06-01"})
        resp.raise_for_status()
        data = resp.json()
        for b in data.get("content", []):
            if b.get("type") == "text":
                yield LLMEvent(type="text_delta", text=b.get("text", ""))
            elif b.get("type") == "tool_use":
                yield LLMEvent(type="tool_use", tool_use={
                    "id": b["id"], "name": b["name"], "input": b.get("input", {})})
        yield LLMEvent(type="done")

    async def probe(self) -> bool:
        body = {
            "model": self.cfg.model,
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "用 force_tool 工具回答 one"}],
            "tools": [{"name": "force_tool", "description": "always call",
                       "input_schema": {"type": "object",
                                        "properties": {"x": {"type": "string"}},
                                        "required": ["x"]}}],
        }
        resp = await self._http.post(self._url(), json=body,
                                     headers={"x-api-key": self.cfg.api_key,
                                              "anthropic-version": "2023-06-01"})
        data = resp.json()
        return any(b.get("type") == "tool_use" for b in data.get("content", []))
```

- [ ] **Step 4: 运行验证通过**

Run: `uv run pytest tests/test_llm_raw.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/taskpanel/core/llm_raw.py tests/test_llm_raw.py
git commit -m "feat: RawHTTPClient 兜底(SSE 解析 + probe)"
```

---

### Task 6: 工具集 `core/tools.py`

**Files:**
- Create: `taskpanel/src/taskpanel/core/tools.py`
- Test: `taskpanel/tests/test_tools.py`

**Interfaces:**
- Consumes: `core.task.Task`
- Produces:
  - `BUILTIN_TOOLS: list[dict]` — `read_file`/`write_file`/`bash` 的 Anthropic tool 定义。
  - `def chat_tools() -> list[dict]` 返回空列表(chat 任务无工具)。
  - `async def execute_tool(name: str, args: dict, task: Task, root: str) -> str` — 返回工具结果字符串;**只允许写 `root` 目录内**;`bash` 设置 `cwd=root`。越权返回错误串。
  - 每条规则: `write_file` 校验 `args["path"]` 解析后在 `root` 内(`Path.resolve().is_relative_to(root)`)。

- [ ] **Step 1: 写失败测试**

`tests/test_tools.py`:
```python
import pytest
from taskpanel.core.tools import execute_tool, BUILTIN_TOOLS
from taskpanel.core.task import make_task


@pytest.mark.asyncio
async def test_read_write_roundtrip(tmp_path):
    t = make_task("project", "x", cwd=str(tmp_path))
    out = await execute_tool("write_file",
                             {"path": "a.txt", "content": "hello"}, t, str(tmp_path))
    assert "ok" in out
    out2 = await execute_tool("read_file", {"path": "a.txt"}, t, str(tmp_path))
    assert "hello" in out2


@pytest.mark.asyncio
async def test_write_outside_root_rejected(tmp_path, tmp_path_factory):
    other = tmp_path_factory.mktemp("evil")
    t = make_task("project", "x", cwd=str(tmp_path))
    out = await execute_tool("write_file",
                             {"path": str(other / "pwn.txt"), "content": "x"}, t, str(tmp_path))
    assert "拒绝" in out


@pytest.mark.asyncio
async def test_bash_cwd_is_root(tmp_path):
    t = make_task("project", "x", cwd=str(tmp_path))
    out = await execute_tool("bash", {"cmd": "pwd"}, t, str(tmp_path))
    assert str(tmp_path) in out


def test_tools_schema():
    names = {t["name"] for t in BUILTIN_TOOLS}
    assert names == {"read_file", "write_file", "bash"}
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_tools.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/taskpanel/core/tools.py`:
```python
from __future__ import annotations
import asyncio
from pathlib import Path

from taskpanel.core.task import Task

BUILTIN_TOOLS = [
    {"name": "read_file", "description": "读取文件内容",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"}},
                      "required": ["path"]}},
    {"name": "write_file", "description": "写入文件(仅限工作区)",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "bash", "description": "在工作区目录运行 shell 命令",
     "input_schema": {"type": "object",
                      "properties": {"cmd": {"type": "string"}},
                      "required": ["cmd"]}},
]


def chat_tools() -> list[dict]:
    return []


def _in_root(path: str, root: str) -> bool:
    p = Path(path).expanduser().resolve()
    r = Path(root).expanduser().resolve()
    return p.is_relative_to(r)


async def execute_tool(name: str, args: dict, task: Task, root: str) -> str:
    root = str(Path(root).expanduser().resolve())
    try:
        if name == "read_file":
            p = str(Path(args["path"]).expanduser().resolve())
            if not _in_root(p, root):
                return "拒绝:路径在工作区之外"
            return Path(p).read_text(encoding="utf-8", errors="replace")
        if name == "write_file":
            p = str(Path(args["path"]).expanduser().resolve())
            if not _in_root(p, root):
                return "拒绝:路径在工作区之外"
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            Path(p).write_text(args["content"], encoding="utf-8")
            return "ok"
        if name == "bash":
            proc = await asyncio.create_subprocess_shell(
                args["cmd"], cwd=root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
            return (out.decode("utf-8", "replace") + err.decode("utf-8", "replace")).strip() or "(空输出)"
        return f"未知工具 {name}"
    except Exception as e:  # noqa: BLE001
        return f"工具执行出错: {e}"
```

- [ ] **Step 4: 运行验证通过**

Run: `uv run pytest tests/test_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/taskpanel/core/tools.py tests/test_tools.py
git commit -m "feat: 内置工具(read_file/write_file/bash, 工作区约束)"
```

---

### Task 7: AgentLoop 工具循环 `core/agent_loop.py`

**Files:**
- Create: `taskpanel/src/taskpanel/core/agent_loop.py`
- Test: `taskpanel/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `core.task.Task`、`core.llm.LLMClient/LLMEvent`、`core.tools.execute_tool`
- Produces:
  - `class AgentLoop:` 构造 `(task: Task, client: LLMClient, tools: list[dict], root: str, emit: Callable[[dict], Awaitable[None]], max_rounds: int = 20)`
  - `async def run(self) -> TaskState` — 全循环:发送 `task.messages` → 流式收集文本/tool_use → 有工具则逐个执行、`emit` tool_result、追加消息 → 重复;无工具则把 assistant 最终消息追加进 `task.messages`,返回 `DONE`;中途 `cancel()` 置 `PAUSED` 并停止。
  - `async def follow_up(self, user_text: str) -> TaskState` — 追加 user 消息后调用 `run()`。
  - `def cancel(self)` — 请求停止。
  - 事件 dict 格式:`{"type":"text_delta","text":...}` / `{"type":"tool_use","tool_use":{...}}` / `{"type":"tool_result","tool_use_id":...,"content":...}` / `{"type":"status","status":...}`。

- [ ] **Step 1: 写失败测试**

`tests/test_agent_loop.py`:
```python
import pytest
from taskpanel.core.agent_loop import AgentLoop
from taskpanel.core.llm import LLMClient, LLMEvent
from taskpanel.core.task import Task, TaskState, make_task


class FakeClient(LLMClient):
    def __init__(self, script):
        """script: list[list[LLMEvent]] 每轮返回的事件列表"""
        self.script = script
        self.i = 0
    async def stream(self, messages, tools=None):
        for ev in self.script[self.i]:
            yield ev
        self.i += 1
    async def probe(self):
        return True


@pytest.mark.asyncio
async def test_run_no_tools_finalizes():
    task = make_task("chat", "hi")
    emitted = []
    loop = AgentLoop(task, FakeClient([[LLMEvent("text_delta", text="hello"),
                                        LLMEvent("done")]]),
                     tools=[], root=".", emit=emitted.append)
    state = await loop.run()
    assert state == TaskState.DONE
    assert task.messages[-1]["role"] == "assistant"
    assert any(e["type"] == "text_delta" for e in emitted)


@pytest.mark.asyncio
async def test_run_executes_tool_then_finalizes(tmp_path):
    from taskpanel.core.tools import BUILTIN_TOOLS
    task = make_task("project", "run pwd", cwd=str(tmp_path))
    emitted = []
    # 第一轮: 触发 bash;第二轮: 纯文本
    script = [
        [LLMEvent("tool_use", tool_use={"id": "t1", "name": "bash", "input": {"cmd": "pwd"}}),
         LLMEvent("done")],
        [LLMEvent("text_delta", text="done!"), LLMEvent("done")],
    ]
    loop = AgentLoop(task, FakeClient(script), tools=BUILTIN_TOOLS,
                     root=str(tmp_path), emit=emitted.append, max_rounds=3)
    state = await loop.run()
    assert state == TaskState.DONE
    assert any(e["type"] == "tool_result" for e in emitted)
    # 消息历史: user + assistant(tool_use) + user(tool_result) + assistant(最终)
    assert task.messages[1]["content"][0]["type"] == "tool_use"
    assert task.messages[2]["content"][0]["type"] == "tool_result"


@pytest.mark.asyncio
async def test_cancel_pauses(tmp_path):
    task = make_task("chat", "hi")
    emitted = []

    class SlowClient(FakeClient):
        async def stream(self, messages, tools=None):
            yield LLMEvent("text_delta", text="a")
            await __import__("asyncio").sleep(0.05)
            yield LLMEvent("text_delta", text="b")
            yield LLMEvent("done")

    loop = AgentLoop(task, SlowClient([[]]), tools=[], root=".", emit=emitted.append)
    await __import__("asyncio").sleep(0.01)
    loop.cancel()
    state = await loop.run()
    assert state == TaskState.PAUSED
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_agent_loop.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/taskpanel/core/agent_loop.py`:
```python
from __future__ import annotations
import asyncio
from typing import Awaitable, Callable

from taskpanel.core.llm import LLMClient, LLMEvent
from taskpanel.core.task import Task, TaskState
from taskpanel.core.tools import execute_tool

Emit = Callable[[dict], Awaitable[None]]


class AgentLoop:
    def __init__(self, task: Task, client: LLMClient, tools: list[dict],
                 root: str, emit: Emit, max_rounds: int = 20):
        self.task = task
        self.client = client
        self.tools = tools
        self.root = root
        self.emit = emit
        self.max_rounds = max_rounds
        self._stop = asyncio.Event()

    def cancel(self):
        self._stop.set()

    async def _emit(self, event: dict):
        if self.emit is None:
            return
        await self.emit(event)

    async def run(self) -> TaskState:
        self.task.status = TaskState.RUNNING
        self.task.touch()
        await self._emit({"type": "status", "status": self.task.status.value})
        rounds = 0
        while rounds < self.max_rounds and not self._stop.is_set():
            rounds += 1
            text_buf = []
            tool_calls: list[dict] = []
            async for ev in self.client.stream(self.task.messages, self.tools):
                if self._stop.is_set():
                    break
                if ev.type == "text_delta":
                    text_buf.append(ev.text)
                    await self._emit({"type": "text_delta", "text": ev.text})
                elif ev.type == "tool_use":
                    tool_calls.append(ev.tool_use)
                    await self._emit({"type": "tool_use", "tool_use": ev.tool_use})
                elif ev.type == "error":
                    self.task.status = TaskState.ERROR
                    self.task.error = ev.error
                    self.task.touch()
                    await self._emit({"type": "error", "error": ev.error})
                    return TaskState.ERROR
            if self._stop.is_set():
                break
            if not tool_calls:
                final_text = "".join(text_buf)
                if final_text:
                    self.task.messages.append(
                        {"role": "assistant",
                         "content": [{"type": "text", "text": final_text}]})
                self.task.status = TaskState.DONE
                self.task.touch()
                await self._emit({"type": "status", "status": self.task.status.value})
                return TaskState.DONE
            # 追加 assistant(tool_use) 与 tool_result,执行工具
            self.task.messages.append(
                {"role": "assistant",
                 "content": [{"type": "tool_use", **c} for c in tool_calls]})
            for c in tool_calls:
                result = await execute_tool(c["name"], c.get("input", {}),
                                            self.task, self.root)
                self.task.messages.append(
                    {"role": "user",
                     "content": [{"type": "tool_result",
                                  "tool_use_id": c["id"], "content": result}]})
                await self._emit({"type": "tool_result",
                                  "tool_use_id": c["id"], "content": result})
        # 超轮次或被打断
        self.task.status = TaskState.PAUSED if self._stop.is_set() else TaskState.PAUSED
        self.task.touch()
        await self._emit({"type": "status", "status": self.task.status.value})
        return TaskState.PAUSED

    async def follow_up(self, user_text: str) -> TaskState:
        self._stop.clear()
        self.task.messages.append(
            {"role": "user",
             "content": [{"type": "text", "text": user_text}]})
        return await self.run()
```

- [ ] **Step 4: 运行验证通过**

Run: `uv run pytest tests/test_agent_loop.py -v`
Expected: PASS(3 tests;注意 `test_cancel_pauses` 中 `emit=emitted.append` 是同步函数——实现里 `await self.emit(...)` 对同步可调用会失败。见下 Step 4b)

- [ ] **Step 4b: 兼容同步 emit(修正)**

将 `agent_loop.py` 中 `_emit` 改为:
```python
    async def _emit(self, event: dict):
        if self.emit is None:
            return
        res = self.emit(event)
        if hasattr(res, "__await__"):
            await res
```
(测试里用同步 `list.append`,生产由 web 层传异步 emit。)

- [ ] **Step 5: 运行验证通过(复跑)**

Run: `uv run pytest tests/test_agent_loop.py -v`
Expected: PASS(3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/taskpanel/core/agent_loop.py tests/test_agent_loop.py
git commit -m "feat: AgentLoop 工具循环(独立消息历史, cancel/follow_up)"
```

---

### Task 8: 持久化 `store/store.py`

**Files:**
- Create: `taskpanel/src/taskpanel/store/store.py`
- Test: `taskpanel/tests/test_store.py`

**Interfaces:**
- Consumes: `core.task.Task/TaskState/make_task`
- Produces:
  - `class TaskStore:` 构造 `(data_dir: Path)`,自动建目录。
  - `def save_task(task: Task) -> None` — 写 `meta.json`(含全部字段)+ 追加 `messages.jsonl` 中尚未落盘的消息。
  - `def append_event(task_id: str, event: dict) -> dict` — 追加 `events.jsonl`,分配自增 `seq`(从文件行数续),返回 `{"seq":..., **event}`。
  - `def load_tasks() -> list[Task]` — 扫描 `data_dir/tasks/*/meta.json`。
  - `def load_messages(task_id) -> list[dict]`。
  - `def events_since(task_id, seq: int) -> list[dict]`。
  - `def delete_task(task_id)`。

- [ ] **Step 1: 写失败测试**

`tests/test_store.py`:
```python
import json
from pathlib import Path
from taskpanel.core.task import make_task
from taskpanel.store.store import TaskStore


def test_save_and_load(tmp_path):
    store = TaskStore(tmp_path)
    t = make_task("chat", "hello world", cwd=None)
    store.save_task(t)
    loaded = store.load_tasks()
    assert len(loaded) == 1 and loaded[0].id == t.id and loaded[0].title == "hello world"


def test_messages_persist(tmp_path):
    store = TaskStore(tmp_path)
    t = make_task("chat", "hi")
    t.messages.append({"role": "user", "content": [{"type": "text", "text": "hi"}]})
    store.save_task(t)
    assert store.load_messages(t.id) == t.messages


def test_events_seq_monotonic(tmp_path):
    store = TaskStore(tmp_path)
    t = make_task("chat", "hi")
    store.save_task(t)
    e1 = store.append_event(t.id, {"type": "text_delta", "text": "a"})
    e2 = store.append_event(t.id, {"type": "text_delta", "text": "b"})
    assert e1["seq"] == 1 and e2["seq"] == 2
    since = store.events_since(t.id, 1)
    assert [e["seq"] for e in since] == [2]


def test_delete(tmp_path):
    store = TaskStore(tmp_path)
    t = make_task("chat", "hi")
    store.save_task(t)
    store.delete_task(t.id)
    assert store.load_tasks() == []
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/taskpanel/store/store.py`:
```python
from __future__ import annotations
import json
from pathlib import Path

from taskpanel.core.task import Task, TaskState


class TaskStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).expanduser()
        self.tasks_dir = self.data_dir / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def _dir(self, task_id: str) -> Path:
        d = self.tasks_dir / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_task(self, task: Task) -> None:
        d = self._dir(task.id)
        meta = {
            "id": task.id, "kind": task.kind, "prompt": task.prompt,
            "cwd": task.cwd, "use_worktree": task.use_worktree,
            "title": task.title, "status": task.status.value,
            "token_count": task.token_count, "created_at": task.created_at,
            "updated_at": task.updated_at, "error": task.error,
            "worktree": task.worktree, "keep_worktree": task.keep_worktree,
        }
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        msg_path = d / "messages.jsonl"
        existing = self.load_messages(task.id)
        new_msgs = task.messages[len(existing):]
        with msg_path.open("a", encoding="utf-8") as f:
            for m in new_msgs:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    def append_event(self, task_id: str, event: dict) -> dict:
        d = self._dir(task_id)
        ev_path = d / "events.jsonl"
        seq = ev_path.read_text(encoding="utf-8").count("\n") if ev_path.exists() else 0
        seq += 1
        full = {"seq": seq, "task_id": task_id, **event}
        with ev_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(full, ensure_ascii=False) + "\n")
        return full

    def load_tasks(self) -> list[Task]:
        tasks = []
        for d in self.tasks_dir.iterdir():
            meta = d / "meta.json"
            if meta.exists():
                tasks.append(self._task_from_meta(json.loads(meta.read_text(encoding="utf-8"))))
        return sorted(tasks, key=lambda t: t.created_at)

    def _task_from_meta(self, m: dict) -> Task:
        return Task(
            id=m["id"], kind=m["kind"], prompt=m["prompt"], cwd=m.get("cwd"),
            use_worktree=m.get("use_worktree", False), title=m["title"],
            status=TaskState(m.get("status", "queued")),
            token_count=m.get("token_count", 0),
            created_at=m.get("created_at", ""), updated_at=m.get("updated_at", ""),
            error=m.get("error"), worktree=m.get("worktree"),
            keep_worktree=m.get("keep_worktree", False),
        )

    def load_messages(self, task_id: str) -> list[dict]:
        p = self._dir(task_id) / "messages.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]

    def events_since(self, task_id: str, seq: int) -> list[dict]:
        p = self._dir(task_id) / "events.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            ev = json.loads(line)
            if ev["seq"] > seq:
                out.append(ev)
        return out

    def delete_task(self, task_id: str) -> None:
        import shutil
        shutil.rmtree(self.tasks_dir / task_id, ignore_errors=True)
```

- [ ] **Step 4: 运行验证通过**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS(4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/taskpanel/store/store.py tests/test_store.py
git commit -m "feat: TaskStore(JSONL 消息/事件 + seq + meta 持久化)"
```

---

### Task 9: worktree 隔离 `store/worktree.py`

**Files:**
- Create: `taskpanel/src/taskpanel/store/worktree.py`
- Test: `taskpanel/tests/test_worktree.py`

**Interfaces:**
- Produces:
  - `class WorktreeManager:` 构造 `(base_dir: Path = ~/.taskpanel/worktrees, auto_cleanup: bool = True, max_retained: int = 5)`
  - `def create(repo: str) -> str` — `git -C <repo> worktree add --detach <base>/<name>`;name 用 `uuid4().hex[:8]`;返回 worktree 路径。
  - `def remove(path: str) -> None` — `git -C <repo> worktree remove --force <path>`;从父路径推导 repo。
  - `def cleanup() -> int` — 找出无对应活跃任务的 stale worktree(由调用方先标记),`remove` 超出 `max_retained` 的,返回清理数。
  - `def _repo_of(path) -> str` — 从 `.git` 文件的 `gitdir:` 头解析主仓库路径。

- [ ] **Step 1: 写失败测试**

`tests/test_worktree.py`:
```python
import subprocess
from pathlib import Path
from taskpanel.store.worktree import WorktreeManager


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.txt").write_text("v1")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def test_create_and_remove(tmp_path):
    repo = _make_repo(tmp_path)
    mgr = WorktreeManager(base_dir=tmp_path / "wt")
    wt = mgr.create(str(repo))
    assert Path(wt).exists()
    assert (Path(wt) / "a.txt").read_text() == "v1"
    mgr.remove(wt)
    assert not Path(wt).exists()
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_worktree.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/taskpanel/store/worktree.py`:
```python
from __future__ import annotations
import subprocess
import uuid
from pathlib import Path


class WorktreeManager:
    def __init__(self, base_dir: Path | None = None,
                 auto_cleanup: bool = True, max_retained: int = 5):
        self.base_dir = Path(base_dir or Path.home() / ".taskpanel" / "worktrees").expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.auto_cleanup = auto_cleanup
        self.max_retained = max_retained

    def create(self, repo: str) -> str:
        name = uuid.uuid4().hex[:8]
        dest = self.base_dir / name
        subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", str(dest)],
                       check=True, capture_output=True)
        return str(dest)

    def _repo_of(self, path: str) -> str:
        gitfile = Path(path) / ".git"
        if gitfile.is_file():
            for line in gitfile.read_text(encoding="utf-8").splitlines():
                if line.startswith("gitdir:"):
                    d = Path(line.split(":", 1)[1].strip())
                    # gitdir 形如 <repo>/.git/worktrees/<name>
                    return str(d.resolve().parent.parent.parent)
        return str(Path(path).parent)

    def remove(self, path: str) -> None:
        repo = self._repo_of(path)
        subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", path],
                       check=False, capture_output=True)

    def cleanup(self) -> int:
        """删除超出 max_retained 的 worktree。调用方应先移走仍活跃的任务,
        否则按创建时间保留最近 max_retained 个。"""
        if not self.base_dir.exists():
            return 0
        wts = sorted(self.base_dir.iterdir(), key=lambda p: p.stat().st_mtime)
        removed = 0
        for wt in wts[:max(0, len(wts) - self.max_retained)]:
            self.remove(str(wt))
            removed += 1
        return removed
```

- [ ] **Step 4: 运行验证通过**

Run: `uv run pytest tests/test_worktree.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/taskpanel/store/worktree.py tests/test_worktree.py
git commit -m "feat: WorktreeManager(git worktree 隔离 + 清理)"
```

---

### Task 10: OCR 子进程包装 `core/ocr.py`

**Files:**
- Create: `taskpanel/src/taskpanel/core/ocr.py`
- Test: `taskpanel/tests/test_ocr.py`

**Interfaces:**
- Produces:
  - `class OcrRunner:` 构造 `(timeout: int = 1800, llm_env: dict | None = None)`;`llm_env` 用于设置 `OCR_LLM_URL/OCR_LLM_TOKEN/OCR_LLM_MODEL/OCR_USE_ANTHROPIC`。
  - `async def llm_test(self) -> bool` — `ocr llm test`,returncode==0。
  - `async def run_review(self, cwd: str, background: str = "", extra: list[str] | None = None) -> dict` — 跑 `ocr review --audience agent [--background ...]`,解析最后一行的 JSON(或失败返回 `{"raw": out, "stderr": err, "ok": False}`)。
  - `async def scan(self, cwd: str, path: str = "") -> dict` — `ocr scan ...`,同解析。
  - 超时用 `asyncio.wait_for`,超时 kill 子进程。

- [ ] **Step 1: 写失败测试**

`tests/test_ocr.py`:
```python
import json
import pytest
from taskpanel.core.ocr import OcrRunner


def _fake_proc(returncode, out, err):
    class P:
        async def communicate(self):
            return out.encode(), err.encode()
    p = P(); p.returncode = returncode
    return p


@pytest.mark.asyncio
async def test_run_review_parses_json(monkeypatch):
    import asyncio
    payload = json.dumps({"findings": [{"file": "a.py", "line": 3}]})
    async def fake_create(*a, **kw):
        return _fake_proc(0, payload, "")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    runner = OcrRunner(timeout=30, llm_env={"OCR_USE_ANTHROPIC": "true"})
    result = await runner.run_review("repo")
    assert result["ok"] is True
    assert result["findings"][0]["file"] == "a.py"


@pytest.mark.asyncio
async def test_run_review_non_json_falls_back(monkeypatch):
    import asyncio
    async def fake_create(*a, **kw):
        return _fake_proc(1, "not json at all", "boom")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    runner = OcrRunner(timeout=30)
    result = await runner.run_review("repo")
    assert result["ok"] is False
    assert "boom" in result["stderr"]
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_ocr.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/taskpanel/core/ocr.py`:
```python
from __future__ import annotations
import asyncio
import json


class OcrRunner:
    def __init__(self, timeout: int = 1800, llm_env: dict | None = None):
        self.timeout = timeout
        self.llm_env = llm_env or {}

    def _env(self):
        env = dict(self.llm_env)
        if env.get("OCR_LLM_URL") and env.get("OCR_LLM_TOKEN"):
            env.setdefault("OCR_USE_ANTHROPIC", "true")
        return env

    async def _run(self, cwd: str, args: list[str]) -> dict:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**__import__("os").environ, **self._env()})
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"ok": False, "raw": "", "stderr": "OCR 超时被终止", "findings": []}
        stdout = out.decode("utf-8", "replace")
        stderr = err.decode("utf-8", "replace")
        findings = []
        for line in reversed(stdout.strip().splitlines()):
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    findings = data.get("findings", data.get("comments", []))
                    break
            except json.JSONDecodeError:
                continue
        return {"ok": proc.returncode == 0 and findings,
                "raw": stdout, "stderr": stderr, "findings": findings}

    async def llm_test(self) -> bool:
        r = await self._run(".", ["ocr", "llm", "test"])
        return r["ok"]

    async def run_review(self, cwd: str, background: str = "",
                         extra: list[str] | None = None) -> dict:
        args = ["ocr", "review", "--audience", "agent"]
        if background:
            args += ["--background", background]
        args += extra or []
        return await self._run(cwd, args)

    async def scan(self, cwd: str, path: str = "") -> dict:
        args = ["ocr", "scan"] + ([path] if path else [])
        return await self._run(cwd, args)
```

- [ ] **Step 4: 运行验证通过**

Run: `uv run pytest tests/test_ocr.py -v`
Expected: PASS(2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/taskpanel/core/ocr.py tests/test_ocr.py
git commit -m "feat: OcrRunner 子进程包装(超时 kill + JSON/Raw 兜底)"
```

---

### Task 11: Web 后端 Manager 与 REST API

**Files:**
- Create: `taskpanel/src/taskpanel/web/manager.py`
- Create: `taskpanel/src/taskpanel/web/server.py`
- Test: `taskpanel/tests/test_api.py`

**Interfaces:**
- Consumes: `core.config.PanelConfig`、`core.task.make_task`、`core.llm.build_client`、`core.agent_loop.AgentLoop`、`core.tools.BUILTIN_TOOLS/chat_tools`、`core.ocr.OcrRunner`、`store.store.TaskStore`、`store.worktree.WorktreeManager`
- Produces:
  - `class Manager:` 构造 `(cfg: PanelConfig)`
    - `async def startup()` — 建 store/wt/ocr;生成/读取 `~/.taskpanel/.auth_token`;启动 worktree 清理任务。
    - `def auth_token() -> str`
    - `async def create_task(kind, prompt, cwd=None, use_worktree=False) -> Task` — 建任务,`project` 且 `use_worktree` 则 `wt.create(cwd)` 作为 root;立即 `store.save_task`;若有并发空位则 `asyncio.create_task(self._dispatch(task))`。
    - `async def _dispatch(task)` — 能力探测(工具列表:probe 失败→空列表,降级纯文本);并发信号量(`cfg.max_parallel`,None→不限);`AgentLoop` emit 回调 = `store.append_event` + 广播。
    - `def subscribe(ws) / def broadcast(event)` — 维护 WS 订阅集合。
    - `def get(task_id) -> Task`、`def list_tasks() -> list[Task]`、`def events_since(task_id, seq)`、`async def follow_up(task_id, text)`、`async def stop(task_id)`(loop.cancel)、`async def delete(task_id)`。
  - `app = create_app(cfg) -> FastAPI` — 端点见 spec §7.1,全部经 `Depends(auth)`,WS 用 query `token`;`GET /api/bootstrap` 返回 token;静态托管 `web/static`(存在时)。

- [ ] **Step 1: 写失败测试**

`tests/test_api.py`:
```python
import pytest
from fastapi.testclient import TestClient
from taskpanel.core.config import PanelConfig, LLMConfig
from taskpanel.web.server import create_app
from taskpanel.web.manager import Manager


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = PanelConfig(
        llm=LLMConfig(base_url="http://localhost:9999/v1", api_key="k", model="m"),
        data_dir=tmp_path / "data", bind_port=1)
    app = create_app(cfg)
    return TestClient(app)


def test_bootstrap_returns_token(client):
    r = client.get("/api/bootstrap")
    assert r.status_code == 200
    assert "token" in r.json()


def test_auth_required(client):
    r = client.get("/api/tasks")
    assert r.status_code == 401


def test_create_list_delete(client):
    token = client.get("/api/bootstrap").json()["token"]
    h = {"X-Auth-Token": token}
    r = client.post("/api/tasks", json={"kind": "chat", "prompt": "你好"},
                    headers=h)
    assert r.status_code == 200
    task_id = r.json()["id"]
    lst = client.get("/api/tasks", headers=h).json()
    assert any(t["id"] == task_id for t in lst)
    r = client.delete(f"/api/tasks/{task_id}", headers=h)
    assert r.status_code == 200
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `web/manager.py`**

`src/taskpanel/web/manager.py`:
```python
from __future__ import annotations
import asyncio
import secrets
from pathlib import Path

from taskpanel.core.config import PanelConfig
from taskpanel.core.task import Task, make_task
from taskpanel.core.llm import build_client, LLMClient
from taskpanel.core.agent_loop import AgentLoop
from taskpanel.core.tools import BUILTIN_TOOLS, chat_tools
from taskpanel.core.ocr import OcrRunner
from taskpanel.store.store import TaskStore
from taskpanel.store.worktree import WorktreeManager


class Manager:
    def __init__(self, cfg: PanelConfig):
        self.cfg = cfg
        self.store: TaskStore | None = None
        self.wt: WorktreeManager | None = None
        self.ocr = OcrRunner(timeout=cfg.ocr_timeout)
        self._token: str | None = None
        self._loops: dict[str, AgentLoop] = {}
        self._subs: set[asyncio.Queue] = set()
        self._sem: asyncio.Semaphore | None = None
        self._probe_cache: dict[tuple, bool] = {}

    async def startup(self):
        self.store = TaskStore(self.cfg.data_dir)
        self.wt = WorktreeManager(auto_cleanup=self.cfg.worktree_auto_cleanup,
                                  max_retained=self.cfg.max_retained_worktrees)
        if self.cfg.max_parallel:
            self._sem = asyncio.Semaphore(self.cfg.max_parallel)
        tok_path = self.cfg.data_dir / ".auth_token"
        if tok_path.exists():
            self._token = tok_path.read_text(encoding="utf-8").strip()
        else:
            self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
            self._token = secrets.token_hex(16)
            tok_path.write_text(self._token, encoding="utf-8")
            try:
                tok_path.chmod(0o600)
            except OSError:
                pass
        if self.cfg.worktree_auto_cleanup:
            asyncio.create_task(self._cleanup_loop())

    def auth_token(self) -> str:
        assert self._token
        return self._token

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(600)
            if self.wt:
                self.wt.cleanup()

    async def _root_for(self, task: Task) -> str:
        if task.use_worktree and task.cwd and self.wt:
            wt = self.wt.create(task.cwd)
            task.worktree = wt
            self.store.save_task(task)
            return wt
        return task.cwd or "."

    async def create_task(self, kind, prompt, cwd=None,
                          use_worktree=False) -> Task:
        task = make_task(kind, prompt, cwd=cwd, use_worktree=use_worktree)
        self.store.save_task(task)
        if self._sem is not None:
            await self._sem.acquire()
        asyncio.create_task(self._dispatch(task))
        return task

    async def _dispatch(self, task: Task):
        try:
            root = await self._root_for(task)
            client = build_client(self.cfg.llm)
            key = (self.cfg.llm.base_url, self.cfg.llm.model)
            if key not in self._probe_cache:
                try:
                    self._probe_cache[key] = await client.probe()
                except Exception:
                    self._probe_cache[key] = False
            tools = BUILTIN_TOOLS if (task.kind == "project" and self._probe_cache[key]) else chat_tools()
            loop = AgentLoop(task, client, tools, root,
                             emit=self._emit_for(task.id),
                             max_rounds=self.cfg.llm.max_tool_rounds)
            self._loops[task.id] = loop
            await loop.run()
            self.store.save_task(task)
        except Exception as e:  # noqa: BLE001
            task.status = __import__("taskpanel.core.task", fromlist=["TaskState"]).TaskState.ERROR
            task.error = str(e)
            self.store.save_task(task)
            await self.broadcast({"type": "error", "task_id": task.id, "error": str(e)})
        finally:
            if self._sem is not None:
                self._sem.release()
            self._loops.pop(task.id, None)

    def _emit_for(self, task_id: str):
        async def emit(event: dict):
            full = self.store.append_event(task_id, event)
            await self.broadcast(full)
            # 顺带把文本/tool 结果也持久化进消息历史
            if event["type"] in ("text_delta", "tool_result"):
                pass  # 消息历史由 AgentLoop 在结束/工具轮时统一写
        return emit

    async def broadcast(self, event: dict):
        for q in list(self._subs):
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subs.discard(q)

    def get(self, task_id: str) -> Task:
        return self.store.get_or_none(task_id)

    def list_tasks(self) -> list[Task]:
        return self.store.load_tasks()

    def events_since(self, task_id: str, seq: int):
        return self.store.events_since(task_id, seq)

    async def follow_up(self, task_id: str, text: str):
        loop = self._loops.get(task_id)
        task = self.get(task_id)
        if loop and task:
            asyncio.create_task(self._run_follow(loop, task, text))
            return {"status": "queued"}
        if task:
            # 已完成任务: 新建 loop
            client = build_client(self.cfg.llm)
            loop = AgentLoop(task, client, chat_tools(), task.cwd or ".",
                             emit=self._emit_for(task.id),
                             max_rounds=self.cfg.llm.max_tool_rounds)
            self._loops[task_id] = loop
            asyncio.create_task(self._run_follow(loop, task, text))
            return {"status": "queued"}
        raise KeyError(task_id)

    async def _run_follow(self, loop, task, text):
        try:
            await loop.follow_up(text)
            self.store.save_task(task)
        finally:
            self._loops.pop(task.id, None)

    async def stop(self, task_id: str):
        loop = self._loops.get(task_id)
        if loop:
            loop.cancel()

    async def delete(self, task_id: str):
        loop = self._loops.get(task_id)
        if loop:
            loop.cancel()
        self.store.delete_task(task_id)
```

- [ ] **Step 3b: 加固 `_dispatch`(重试 + 协议回退 + 工具选择统一)**

将工具选择抽成 helper,并对首次运行协议错误做一次 SDK→Raw 回退、对运行异常做指数退避重试。在 `Manager` 增加:

```python
    def _tools_for(self, task: Task) -> list[dict]:
        if task.kind != "project":
            return chat_tools()
        key = (self.cfg.llm.base_url, self.cfg.llm.model)
        if key not in self._probe_cache:
            return chat_tools()  # 探测未完成,先用纯文本
        return BUILTIN_TOOLS if self._probe_cache[key] else chat_tools()
```

替换 `_dispatch` 主体:

```python
    async def _dispatch(self, task: Task):
        root = await self._root_for(task)
        client = build_client(self.cfg.llm)
        try:
            key = (self.cfg.llm.base_url, self.cfg.llm.model)
            if key not in self._probe_cache:
                try:
                    self._probe_cache[key] = await client.probe()
                except Exception:
                    self._probe_cache[key] = False
            tools = self._tools_for(task)
            loop = AgentLoop(task, client, tools, root,
                             emit=self._emit_for(task.id),
                             max_rounds=self.cfg.llm.max_tool_rounds)
            self._loops[task.id] = loop
            last_err = None
            for attempt in range(self.cfg.llm.max_retries):
                try:
                    await loop.run()
                    self.store.save_task(task)
                    return
                except Exception as e:  # noqa: BLE001 协议/网络错误
                    last_err = e
                    if attempt == 0 and isinstance(client, AnthropicSDKClient):
                        from taskpanel.core.llm_raw import RawHTTPClient
                        client = RawHTTPClient(self.cfg.llm)  # SDK 协议错 → 回退 raw
                        loop = AgentLoop(task, client, tools, root,
                                         emit=self._emit_for(task.id),
                                         max_rounds=self.cfg.llm.max_tool_rounds)
                        self._loops[task.id] = loop
                    await asyncio.sleep(2 ** attempt)
            raise last_err
        except Exception as e:  # noqa: BLE001
            task.status = TaskState.ERROR
            task.error = str(e)
            self.store.save_task(task)
            await self.broadcast({"type": "error", "task_id": task.id, "error": str(e)})
        finally:
            if self._sem is not None:
                self._sem.release()
            self._loops.pop(task.id, None)
```

(顶部 import 增加 `from taskpanel.core.llm import AnthropicSDKClient` 与 `from taskpanel.core.task import TaskState`;`follow_up` 里 `chat_tools()` 换成 `self._tools_for(task)`。)

- [ ] **Step 4: 给 `store.py` 补 `get_or_none`**

在 `TaskStore` 加:
```python
    def get_or_none(self, task_id: str) -> Task | None:
        meta = self.tasks_dir / task_id / "meta.json"
        if not meta.exists():
            return None
        return self._task_from_meta(json.loads(meta.read_text(encoding="utf-8")))
```

- [ ] **Step 5: 实现 `web/server.py`**

`src/taskpanel/web/server.py`:
```python
from __future__ import annotations
import asyncio
from fastapi import FastAPI, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from taskpanel.core.config import PanelConfig
from taskpanel.web.manager import Manager


class CreateBody(BaseModel):
    kind: str = "chat"
    prompt: str
    cwd: str | None = None
    use_worktree: bool = False


class FollowBody(BaseModel):
    text: str


def create_app(cfg: PanelConfig) -> FastAPI:
    app = FastAPI()
    mgr = Manager(cfg)

    @app.on_event("startup")
    async def _startup():
        await mgr.startup()

    def auth(x_auth_token: str = Header(default="")):
        if x_auth_token != mgr.auth_token():
            raise HTTPException(401, "invalid token")

    @app.get("/api/bootstrap")
    async def bootstrap():
        return {"token": mgr.auth_token()}

    @app.get("/api/tasks", dependencies=[Depends(auth)])
    async def list_tasks():
        return [t.__dict__ | {"status": t.status.value} for t in mgr.list_tasks()]

    @app.post("/api/tasks", dependencies=[Depends(auth)])
    async def create_task(body: CreateBody):
        t = await mgr.create_task(body.kind, body.prompt, body.cwd, body.use_worktree)
        return t.__dict__ | {"status": t.status.value}

    @app.get("/api/tasks/{task_id}", dependencies=[Depends(auth)])
    async def get_task(task_id: str):
        t = mgr.get(task_id)
        if not t:
            raise HTTPException(404, "task not found")
        return t.__dict__ | {"status": t.status.value, "messages": t.messages}

    @app.post("/api/tasks/{task_id}/messages", dependencies=[Depends(auth)])
    async def follow_up(task_id: str, body: FollowBody):
        try:
            return await mgr.follow_up(task_id, body.text)
        except KeyError:
            raise HTTPException(404, "task not found")

    @app.post("/api/tasks/{task_id}/stop", dependencies=[Depends(auth)])
    async def stop(task_id: str):
        await mgr.stop(task_id)
        return {"ok": True}

    @app.delete("/api/tasks/{task_id}", dependencies=[Depends(auth)])
    async def delete(task_id: str):
        await mgr.delete(task_id)
        return {"ok": True}

    @app.get("/api/tasks/{task_id}/events", dependencies=[Depends(auth)])
    async def events(task_id: str, since: int = Query(0)):
        return mgr.events_since(task_id, since)

    @app.websocket("/ws/tasks")
    async def ws(ws: WebSocket, token: str = Query("")):
        if token != mgr.auth_token():
            await ws.close(code=4401)
            return
        await ws.accept()
        q = mgr.subscribe()
        try:
            while True:
                event = await q.get()
                await ws.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            mgr.unsubscribe(q)

    import os
    static = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static):
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app
```

- [ ] **Step 6: 运行验证通过**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS(3 tests)

- [ ] **Step 7: Commit**

```bash
git add src/taskpanel/web/manager.py src/taskpanel/web/server.py src/taskpanel/store/store.py tests/test_api.py
git commit -m "feat: Web 后端 Manager + REST API + token 鉴权"
```

---

### Task 12: WebSocket 事件推送与断线补齐

**Files:**
- Modify: `taskpanel/src/taskpanel/web/server.py`
- Modify: `taskpanel/src/taskpanel/web/manager.py`
- Test: `taskpanel/tests/test_ws.py`

**Interfaces:**
- Consumes: Task 11 全部。
- Produces:
  - WS 连接接受 `?token=` 与 `?last_event_id=`,连接建立后先补发 `events_since(last_event_id)` 的存量事件,再进入实时推送循环。
  - `Manager.events_since(task_id, seq)` 已就绪;新增 WS 全局补发按任务聚合:`GET /api/tasks/{id}/events?since=` 已就绪。

- [ ] **Step 1: 写失败测试**

`tests/test_ws.py`:
```python
import pytest
from fastapi.testclient import TestClient
from taskpanel.core.config import PanelConfig, LLMConfig
from taskpanel.web.server import create_app


@pytest.fixture
def client(tmp_path):
    cfg = PanelConfig(llm=LLMConfig(base_url="http://x", api_key="k", model="m"),
                      data_dir=tmp_path / "data")
    return TestClient(create_app(cfg))


def test_ws_requires_token(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/tasks") as ws:
            ws.receive_json()
    assert exc.value.code == 4401
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_ws.py -v`
Expected: FAIL(期望 4401 关闭)

- [ ] **Step 3: 补测试:合法 token 收到事件(先建任务再订阅)**

`tests/test_ws.py` 追加:
```python
def test_ws_receives_events_and_replays(client):
    token = client.get("/api/bootstrap").json()["token"]
    h = {"X-Auth-Token": token}
    t = client.post("/api/tasks", json={"kind": "chat", "prompt": "hi"}, headers=h).json()
    # 产生一个事件(直接调 store 不易,用 stop 触发 status 变更不可靠)——
    # 改为: 订阅后建第二个任务,应收到 status/queued 事件。
    with client.websocket_connect(f"/ws/tasks?token={token}") as ws:
        t2 = client.post("/api/tasks", json={"kind": "chat", "prompt": "hi2"}, headers=h).json()
        got = ws.receive_json()
        assert got["type"] == "status"
        assert got["task_id"] == t2["id"]
```

- [ ] **Step 4: 实现 WS 补发逻辑**

修改 `server.py` 的 `ws` 端点:
```python
    @app.websocket("/ws/tasks")
    async def ws(ws: WebSocket, token: str = Query(""),
                 last_event_id: int = Query(0)):
        if token != mgr.auth_token():
            await ws.close(code=4401)
            return
        await ws.accept()
        # 断线补齐: 补发所有任务 seq > last_event_id 的事件
        for task in mgr.list_tasks():
            for ev in mgr.events_since(task.id, last_event_id):
                await ws.send_json(ev)
        q = mgr.subscribe()
        try:
            while True:
                event = await q.get()
                if event["seq"] <= last_event_id:
                    continue
                await ws.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            mgr.unsubscribe(q)
```

- [ ] **Step 5: 运行验证通过**

Run: `uv run pytest tests/test_ws.py -v`
Expected: PASS(2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/taskpanel/web/server.py tests/test_ws.py
git commit -m "feat: WS 事件推送 + 断线按 seq 补齐"
```

---

### Task 13: 前端脚手架 + API/WS 客户端

**Files:**
- Create: `taskpanel/frontend/package.json`
- Create: `taskpanel/frontend/vite.config.js`
- Create: `taskpanel/frontend/index.html`
- Create: `taskpanel/frontend/src/main.jsx`
- Create: `taskpanel/frontend/src/api.js`
- Create: `taskpanel/frontend/src/App.jsx`(占位)

**Interfaces:**
- Produces:
  - `npm run dev` 起 Vite(代理 `/api`、`/ws` 到 `http://127.0.0.1:8470`);`npm run build` 产出到 `../src/taskpanel/web/static`(由后端静态托管)。
  - `api.js` 导出:
    - `async function bootstrap() -> {token}`
    - `async function createTask({kind,prompt,cwd,use_worktree})`
    - `async function listTasks()`
    - `async function getTask(id)`
    - `async function sendMessage(id, text)`
    - `async function stopTask(id)`, `async function deleteTask(id)`
    - `async function fetchEvents(id, since)`
    - `function connectWS(onEvent) -> {close}` — 携带 token + 维护 `lastEventId`,断线自动重连,重连后先 `fetchEvents` 补齐再续流。
  - 全局 `window.__api` 便于测试。

- [ ] **Step 1: 写 `package.json`**

```json
{
  "name": "taskpanel-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 2: 写 `vite.config.js`**

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8470',
      '/ws': { target: 'ws://127.0.0.1:8470', ws: true },
    },
  },
  build: { outDir: '../src/taskpanel/web/static', emptyOutDir: true },
})
```

- [ ] **Step 3: 写 `index.html`**

```html
<!doctype html>
<html lang="zh">
<head><meta charset="UTF-8"><title>TaskPanel</title></head>
<body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body>
</html>
```

- [ ] **Step 4: 写 `src/api.js`**

```js
let TOKEN = null
let LAST_EVENT_ID = 0

async function jsonFetch(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) }
  if (TOKEN) headers['X-Auth-Token'] = TOKEN
  const res = await fetch(path, { ...opts, headers })
  if (res.status === 401) throw new Error('auth failed')
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

export async function bootstrap() {
  const data = await jsonFetch('/api/bootstrap')
  TOKEN = data.token
  return data
}
export const createTask = (body) => jsonFetch('/api/tasks', { method: 'POST', body: JSON.stringify(body) })
export const listTasks = () => jsonFetch('/api/tasks')
export const getTask = (id) => jsonFetch(`/api/tasks/${id}`)
export const sendMessage = (id, text) => jsonFetch(`/api/tasks/${id}/messages`, { method: 'POST', body: JSON.stringify({ text }) })
export const stopTask = (id) => jsonFetch(`/api/tasks/${id}/stop`, { method: 'POST' })
export const deleteTask = (id) => jsonFetch(`/api/tasks/${id}`, { method: 'DELETE' })
export const fetchEvents = (id, since) => jsonFetch(`/api/tasks/${id}/events?since=${since}`)

export function connectWS(onEvent) {
  let ws, closed = false, retry = 0
  const url = `ws://${location.host}/ws/tasks?token=${encodeURIComponent(TOKEN)}&last_event_id=${LAST_EVENT_ID}`
  function open() {
    ws = new WebSocket(url)
    ws.onmessage = (ev) => {
      const e = JSON.parse(ev.data)
      if (e.seq > LAST_EVENT_ID) LAST_EVENT_ID = e.seq
      onEvent(e)
    }
    ws.onclose = () => { if (!closed) setTimeout(reconnect, Math.min(1000 * 2 ** retry++, 15000)) }
    ws.onopen = () => { retry = 0 }
  }
  async function reconnect() {
    // 用 REST 补齐可能错过的增量(断线期间的事件由服务端 events_since 补)
    onEvent({ type: 'reconnect' })
    open()
  }
  open()
  return { close() { closed = true; ws?.close() } }
}
```

- [ ] **Step 5: 写 `src/main.jsx` 与占位 `App.jsx`**

`main.jsx`:
```jsx
import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
createRoot(document.getElementById('root')).render(<App />)
```
`App.jsx`(占位,Task 14 实现):
```jsx
export default function App() {
  return <h1>TaskPanel</h1>
}
```

- [ ] **Step 6: 安装并构建**

```bash
cd frontend && npm install && npm run build
```
Expected: 生成 `src/taskpanel/web/static/index.html`。

- [ ] **Step 7: Commit**

```bash
git add frontend src/taskpanel/web/static
git commit -m "feat: 前端脚手架 + REST/WS 客户端(自动重连 + seq 补齐)"
```

---

### Task 14: 三栏 UI(App + Sidebar + ChatPane + StatusBar)

**Files:**
- Create: `taskpanel/frontend/src/App.jsx`(替换占位)
- Create: `taskpanel/frontend/src/components/Sidebar.jsx`
- Create: `taskpanel/frontend/src/components/ChatPane.jsx`
- Create: `taskpanel/frontend/src/components/StatusBar.jsx`
- Create: `taskpanel/frontend/src/styles.css`

**Interfaces:**
- Consumes: `api.js`。
- Produces: 三栏布局组件;`App` 管理 `tasks/selectedId/events` 状态与 WS 订阅。

- [ ] **Step 1: 写 `styles.css`(三栏 + 状态栏)**

```css
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; }
#root { display: flex; flex-direction: column; height: 100vh; }
.main { display: flex; flex: 1; min-height: 0; }
.sidebar { width: 260px; border-right: 1px solid #ddd; padding: 8px; overflow-y: auto; }
.pane { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.review { width: 340px; border-left: 1px solid #ddd; padding: 8px; overflow-y: auto; }
.statusbar { border-top: 1px solid #ddd; padding: 4px 8px; font-size: 12px; display: flex; gap: 16px; }
.task-item { padding: 6px 8px; border-radius: 6px; cursor: pointer; }
.task-item.selected { background: #eef; }
.badge { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.badge.running { background: #4caf50; } .badge.queued { background: #ffc107; }
.badge.done { background: #999; } .badge.error, .badge.stopped { background: #f44336; }
.msgs { flex: 1; overflow-y: auto; padding: 12px; }
.msg { margin-bottom: 10px; white-space: pre-wrap; }
.inputbar { border-top: 1px solid #ddd; padding: 8px; display: flex; gap: 8px; }
.inputbar input { flex: 1; padding: 8px; }
.toolcard { background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px; padding: 8px; margin-bottom: 8px; font-size: 13px; }
```

- [ ] **Step 2: 写 `Sidebar.jsx`**

```jsx
import { useState } from 'react'
import { createTask } from '../api.js'

export default function Sidebar({ tasks, selectedId, onSelect, onTasksChanged }) {
  const [showForm, setShowForm] = useState(false)
  const [kind, setKind] = useState('chat')
  const [prompt, setPrompt] = useState('')
  const [cwd, setCwd] = useState('')
  const [wt, setWt] = useState(false)

  async function submit(e) {
    e.preventDefault()
    await createTask({ kind, prompt, cwd: cwd || null, use_worktree: wt })
    setPrompt(''); setShowForm(false); onTasksChanged()
  }

  const byKind = (k) => tasks.filter((t) => t.kind === k)

  return (
    <aside className="sidebar">
      <button id="new-task-btn" onClick={() => setShowForm((v) => !v)} style={{ width: '100%' }}>
        {showForm ? '收起' : '+ 新建任务 (Ctrl+N)'}
      </button>
      {showForm && (
        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="chat">Chat(不绑定仓库)</option>
            <option value="project">Project(绑定仓库)</option>
          </select>
          {kind === 'project' && (
            <>
              <input placeholder="仓库路径" value={cwd} onChange={(e) => setCwd(e.target.value)} />
              <label><input type="checkbox" checked={wt} onChange={(e) => setWt(e.target.checked)} /> worktree 隔离</label>
            </>
          )}
          <textarea rows={3} placeholder="任务描述" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <button disabled={!prompt}>派发</button>
        </form>
      )}
      <h4>Project</h4>
      {byKind('project').map((t) => <TaskItem key={t.id} t={t} sel={selectedId === t.id} onSelect={onSelect} />)}
      <h4>Chat</h4>
      {byKind('chat').map((t) => <TaskItem key={t.id} t={t} sel={selectedId === t.id} onSelect={onSelect} />)}
    </aside>
  )
}

function TaskItem({ t, sel, onSelect }) {
  return (
    <div className={`task-item${sel ? ' selected' : ''}`} onClick={() => onSelect(t.id)}>
      <span className={`badge ${t.status}`} />
      <strong>{t.title}</strong>
    </div>
  )
}
```

- [ ] **Step 3: 写 `ChatPane.jsx`**

```jsx
import { useState } from 'react'
import { sendMessage, stopTask, deleteTask } from '../api.js'

export default function ChatPane({ task, events, onEventsChanged }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (!text.trim() || busy) return
    setBusy(true)
    await sendMessage(task.id, text)
    setText('')
    setTimeout(() => setBusy(false), 100)
    onEventsChanged()
  }

  const msgs = task?.messages || []
  return (
    <section className="pane">
      <div className="msgs">
        {msgs.map((m, i) => (
          <div key={i} className="msg">
            <b>{m.role}</b>: {m.content.map((c) => (c.type === 'text' ? c.text : `[tool: ${c.type}]`)).join(' ')}
          </div>
        ))}
        {(events.filter((e) => e.type === 'text_delta')).slice(-200).map((e, i) => (
          <span key={i}>{e.text}</span>
        ))}
      </div>
      <form className="inputbar" onSubmit={submit}>
        <input value={text} placeholder="继续对话…" onChange={(e) => setText(e.target.value)} />
        <button disabled={!text.trim() || busy}>发送</button>
        <button type="button" onClick={async () => { await stopTask(task.id) }}>停止</button>
        <button type="button" onClick={async () => { if (confirm('删除任务?')) await deleteTask(task.id); onEventsChanged() }}>删除</button>
      </form>
    </section>
  )
}
```

- [ ] **Step 4: 写 `StatusBar.jsx`**

```jsx
export default function StatusBar({ tasks, wsOk }) {
  const tokens = tasks.reduce((s, t) => s + (t.token_count || 0), 0)
  return (
    <footer className="statusbar">
      <span>任务: {tasks.length}</span>
      <span>Token: {tokens}</span>
      <span>连接: {wsOk ? '✓' : '✗'}</span>
    </footer>
  )
}
```

- [ ] **Step 5: 写 `App.jsx`(状态 + 三栏 + WS)**

```jsx
import { useEffect, useState, useCallback, useRef } from 'react'
import * as api from './api.js'
import Sidebar from './components/Sidebar.jsx'
import ChatPane from './components/ChatPane.jsx'
import StatusBar from './components/StatusBar.jsx'
import './styles.css'

export default function App() {
  const [tasks, setTasks] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [events, setEvents] = useState([])
  const [wsOk, setWsOk] = useState(false)
  const wsRef = useRef(null)

  const refresh = useCallback(async () => {
    setTasks(await api.listTasks())
    setSelectedId((cur) => cur || null)
  }, [])

  useEffect(() => {
    api.bootstrap().then(refresh)
  }, [refresh])

  useEffect(() => {
    wsRef.current = api.connectWS((e) => {
      if (e.type === 'reconnect') { refresh(); return }
      setWsOk(true)
      setEvents((prev) => [...prev.slice(-500), e])
    })
    return () => wsRef.current?.close()
  }, [refresh])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'n' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        document.getElementById('new-task-btn')?.click()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const selected = tasks.find((t) => t.id === selectedId) || null
  return (
    <>
      <div className="main">
        <Sidebar tasks={tasks} selectedId={selectedId} onSelect={setSelectedId} onTasksChanged={refresh} />
        {selected ? <ChatPane task={selected} events={events} onEventsChanged={refresh} />
                  : <div className="pane" style={{ placeContent: 'center', textAlign: 'center', color: '#888' }}>选择左侧任务开始</div>}
      </div>
      <StatusBar tasks={tasks} wsOk={wsOk} />
    </>
  )
}
```

- [ ] **Step 6: 构建**

```bash
cd frontend && npm run build
```
Expected: build 成功。

- [ ] **Step 7: 手动冒烟**

```bash
# 终端 A
uv run uvicorn taskpanel.web.server:app --host 127.0.0.1 --port 8470 --factory  # 需要 --factory,见 Task 16 修正
```
(本任务先只验证前端 build 与 `npm run dev` 能看到三栏;完整联调在 Task 16。)

- [ ] **Step 8: Commit**

```bash
git add frontend/src frontend/package.json frontend/package-lock.json
git commit -m "feat: 三栏 UI(侧栏/对话/状态栏)"
```

---

### Task 15: Review 面板(OCR 结果 + diff 上下文行数)

**Files:**
- Create: `taskpanel/frontend/src/components/ReviewPane.jsx`
- Modify: `taskpanel/frontend/src/App.jsx`(接入右栏,`Esc` 折叠)
- Modify: `taskpanel/src/taskpanel/web/server.py`(`GET /api/tasks/{id}/review`)
- Modify: `taskpanel/src/taskpanel/web/manager.py`(缓存 review 结果)
- Test: `taskpanel/tests/test_review_api.py`

**Interfaces:**
- Produces:
  - `GET /api/tasks/{id}/review` → `{"findings": [...], "raw": str|null, "stderr": str|null}`。
  - `Manager.run_review(task_id, background="")` — 调 `ocr.run_review`,结果存 `self._reviews[task_id]`;`get_review(task_id)` 读取。
  - 前端 `ReviewPane` 展示 findings 列表(severity 筛选)+ Raw/stderr 兜底;diff 预览按 `diff_context_lines` 显示锚点行上下文。

- [ ] **Step 1: 写失败测试**

`tests/test_review_api.py`:
```python
import pytest
from fastapi.testclient import TestClient
from taskpanel.core.config import PanelConfig, LLMConfig
from taskpanel.web.server import create_app
from taskpanel.web.manager import Manager


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = PanelConfig(llm=LLMConfig(base_url="http://x", api_key="k", model="m"),
                      data_dir=tmp_path / "data")
    app = create_app(cfg)

    class FakeOCR:
        async def run_review(self, cwd, background="", extra=None):
            return {"ok": True, "findings": [{"file": "a.py", "line": 3,
                                              "severity": "high", "text": "NPE risk"}],
                    "raw": "", "stderr": ""}

    # 注入 fake
    mgr = app.state._mgr if hasattr(app.state, "_mgr") else None
    return TestClient(app), FakeOCR()


def test_review_endpoint_returns_findings(tmp_path):
    # 简化: 直接构造 Manager 并注入 fake
    import asyncio
    from taskpanel.web.manager import Manager
    cfg = PanelConfig(llm=LLMConfig(base_url="http://x", api_key="k", model="m"),
                      data_dir=tmp_path / "data")
    mgr = Manager(cfg)
    asyncio.run(mgr.startup())

    class FakeOCR:
        async def run_review(self, cwd, background="", extra=None):
            return {"ok": True, "findings": [{"file": "a.py", "line": 3,
                                              "severity": "high", "text": "NPE risk"}],
                    "raw": "", "stderr": ""}
    mgr.ocr = FakeOCR()

    async def scenario():
        t = await mgr.create_task("project", "review", cwd=str(tmp_path))
        await mgr.run_review(t.id)
        return mgr.get_review(t.id)
    r = asyncio.run(scenario())
    assert r["findings"][0]["text"] == "NPE risk"
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_review_api.py -v`
Expected: FAIL

- [ ] **Step 3: Manager 增加 review 方法**

在 `web/manager.py` 增加:
```python
    def __init__(...):
        ...
        self._reviews: dict[str, dict] = {}

    async def run_review(self, task_id: str, background: str = ""):
        task = self.get(task_id)
        if not task:
            raise KeyError(task_id)
        root = task.worktree or task.cwd or "."
        result = await self.ocr.run_review(root, background=background)
        self._reviews[task_id] = result
        return result

    def get_review(self, task_id: str) -> dict:
        return self._reviews.get(task_id, {"findings": [], "raw": None, "stderr": None})

    async def get_context(self, task_id: str, path: str, line: int, context: int = 8) -> dict:
        """返回锚点行 ±context 行的文件内容,供 diff 预览展开。"""
        task = self.get(task_id)
        if not task:
            raise KeyError(task_id)
        root = Path(task.worktree or task.cwd or ".")
        full = Path(path)
        if not full.is_absolute():
            full = root / full
        lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
        lo, hi = max(0, line - 1 - context), min(len(lines), line + context)
        return {"path": str(full), "start": lo + 1, "lines": lines[lo:hi]}
```

- [ ] **Step 4: server 增加端点**

在 `server.py` 增加:
```python
    @app.post("/api/tasks/{task_id}/review", dependencies=[Depends(auth)])
    async def run_review(task_id: str, background: str = ""):
        try:
            return await mgr.run_review(task_id, background)
        except KeyError:
            raise HTTPException(404, "task not found")

    @app.get("/api/tasks/{task_id}/review", dependencies=[Depends(auth)])
    async def get_review(task_id: str):
        return mgr.get_review(task_id)

    @app.get("/api/tasks/{task_id}/context", dependencies=[Depends(auth)])
    async def get_context(task_id: str, path: str, line: int, context: int = 8):
        try:
            return await mgr.get_context(task_id, path, line, context)
        except (KeyError, FileNotFoundError):
            raise HTTPException(404, "not found")
```

- [ ] **Step 5: 运行验证通过**

Run: `uv run pytest tests/test_review_api.py -v`
Expected: PASS

- [ ] **Step 6: 写 `ReviewPane.jsx`(含真实 diff 展开)**

先在 `src/api.js` 追加:
```js
export const getReview = (id) => jsonFetch(`/api/tasks/${id}/review`)
export const fetchContext = (id, path, line, context) =>
  jsonFetch(`/api/tasks/${id}/context?path=${encodeURIComponent(path)}&line=${line}&context=${context}`)
```

再写 `ReviewPane.jsx`:
```jsx
import { useEffect, useState } from 'react'
import { getReview, fetchContext } from '../api.js'

function DiffPreview({ taskId, file, line, context }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    fetchContext(taskId, file, line, context).then(setData).catch(() => setData(null))
  }, [taskId, file, line, context])
  if (!data) return <pre style={{ fontSize: 11, color: '#888' }}>加载中…</pre>
  return (
    <pre style={{ fontSize: 12, maxHeight: 160, overflow: 'auto' }}>
      {data.lines.map((l, i) => {
        const n = data.start + i
        return `${String(n).padStart(4, ' ')} ${n === line ? '▶' : ' '} ${l}`
      }).join('\n')}
    </pre>
  )
}

export default function ReviewPane({ task, diffContext }) {
  const [review, setReview] = useState(null)
  const [severity, setSeverity] = useState('all')
  const [expanded, setExpanded] = useState(null)

  useEffect(() => {
    getReview(task.id).then(setReview).catch(() => setReview(null))
  }, [task.id])

  const findings = review?.findings || []
  const shown = severity === 'all' ? findings : findings.filter((f) => f.severity === severity)
  return (
    <aside className="review">
      <h3>Review</h3>
      <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
        <option value="all">全部</option><option value="high">High</option>
        <option value="medium">Medium</option><option value="low">Low</option>
      </select>
      {shown.length === 0 && <p style={{ color: '#888' }}>暂无发现(右栏可折叠 Esc)</p>}
      {shown.map((f, i) => (
        <div key={i} className="toolcard">
          <b>{f.severity}</b> {f.file}:{f.line}
          <p>{f.text}</p>
          <button onClick={() => setExpanded(expanded === i ? null : i)}>
            {expanded === i ? '收起' : '展开 diff'}
          </button>
          {expanded === i && (
            <DiffPreview taskId={task.id} file={f.file} line={f.line} context={diffContext} />
          )}
        </div>
      ))}
      {review?.raw && <pre style={{ fontSize: 11, color: '#900' }}>{review.raw}</pre>}
    </aside>
  )
}
```

- [ ] **Step 7: App 接入右栏 + Esc 折叠**

修改 `App.jsx`:
```jsx
import ReviewPane from './components/ReviewPane.jsx'
// state:
const [showReview, setShowReview] = useState(true)
useEffect(() => {
  const onKey = (e) => { if (e.key === 'Escape') setShowReview((v) => !v) }
  window.addEventListener('keydown', onKey)
  return () => window.removeEventListener('keydown', onKey)
}, [])
// 布局里 selected && showReview 时:
<ReviewPane task={selected} diffContext={8} />
```

- [ ] **Step 8: 构建 + Commit**

```bash
cd frontend && npm run build
git add frontend/src src/taskpanel/web/server.py src/taskpanel/web/manager.py tests/test_review_api.py
git commit -m "feat: Review 面板(OCR findings 筛选 + 可折叠 diff)"
```

---

### Task 16: 端到端联调 + 启动脚本 + README

**Files:**
- Create: `taskpanel/run.py`(入口)
- Create: `taskpanel/README.md`
- Create: `taskpanel/.env.example`
- Modify: `taskpanel/src/taskpanel/web/server.py`(加 `--factory` 支持)

**Interfaces:**
- Produces:
  - `python run.py` 或 `uv run python run.py` 启动后端(读 `.env`/环境变量,绑定 8470),打印访问地址与前端构建提示。
  - `.env.example` 列出全部 `TASKPANEL_*` 与 `OCR_*` 变量。

- [ ] **Step 1: 写 `run.py`**

```python
from __future__ import annotations
import os
import uvicorn
from dotenv import load_dotenv  # 可选,无则忽略
from taskpanel.core.config import load_config
from taskpanel.web.server import create_app

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    cfg = load_config()
    app = create_app(cfg)
    print(f"TaskPanel → http://{cfg.bind_host}:{cfg.bind_port}")
    uvicorn.run(app, host=cfg.bind_host, port=cfg.bind_port)
```
(如未装 `python-dotenv`,`uv add python-dotenv`。)

- [ ] **Step 2: 写 `.env.example`**

```ini
# 模型后端(你的 DeepSeek↔Anthropic 映射)
TASKPANEL_LLM_BASE_URL=http://127.0.0.1:8000/v1
TASKPANEL_LLM_API_KEY=sk-xxx
TASKPANEL_LLM_MODEL=deepseek-v4
# 并发(留空=不限制)
TASKPANEL_MAX_PARALLEL=
# OCR(open-code-review)后端
OCR_LLM_URL=http://127.0.0.1:8000/v1/messages
OCR_LLM_TOKEN=sk-xxx
OCR_LLM_MODEL=deepseek-v4
OCR_USE_ANTHROPIC=true
# 面板
TASKPANEL_BIND_HOST=127.0.0.1
TASKPANEL_BIND_PORT=8470
```

- [ ] **Step 3: 写 `README.md`**

```markdown
# TaskPanel

本地并行任务面板:每个任务独立上下文,支持普通问答与 OCR 代码审查,Web 三栏 UI。

## 快速开始
1. `npm install`(在 frontend/)并 `npm run build`
2. 复制 `.env.example` 为 `.env`,填 `TASKPANEL_LLM_*` 与 `OCR_*`
3. `npm i -g @alibaba-group/open-code-review`(OCR 依赖)
4. `uv run python run.py` → 浏览器打开 http://127.0.0.1:8470

## 配置
见 `.env.example`。数据落在 `~/.taskpanel/`(任务消息、事件、worktree、auth token)。

## 测试
`uv run pytest`
```

- [ ] **Step 4: 端到端冒烟**

```bash
cd frontend && npm run build
cd .. && cp .env.example .env  # 填入你的 DeepSeek 映射
uv run python run.py
```
Expected: 后端起来,浏览器打开 → 新建一个 chat 任务 → 收到流式回复;新建 project 任务跑 `ocr review` → 右栏出现 findings。

- [ ] **Step 5: Commit**

```bash
git add run.py README.md .env.example src/taskpanel/web/server.py
git commit -m "feat: 启动入口 + README + 端到端联调"
```

---

### Task 17: 加固:长任务中断恢复测试

**Files:**
- Create: `taskpanel/tests/test_interrupt_recovery.py`
- Modify: `taskpanel/src/taskpanel/web/manager.py`(启动时恢复未完成任务为 `paused`)

**Interfaces:**
- Produces:
  - 启动时 `Manager.startup()` 将旧任务状态 `running`→`paused`(不自动重跑,避免崩溃后立即重放)。

- [ ] **Step 1: 写失败测试**

`tests/test_interrupt_recovery.py`:
```python
import json
from pathlib import Path
from taskpanel.core.task import TaskState
from taskpanel.store.store import TaskStore


def test_startup_marks_stale_running_as_paused(tmp_path):
    store = TaskStore(tmp_path)
    t = __import__("taskpanel.core.task", fromlist=["make_task"]).make_task("chat", "hi")
    t.status = TaskState.RUNNING
    store.save_task(t)
    # 模拟 Manager.startup 的恢复逻辑
    from taskpanel.web.manager import Manager
    from taskpanel.core.config import PanelConfig, LLMConfig
    import asyncio
    cfg = PanelConfig(llm=LLMConfig(), data_dir=tmp_path / "data")
    asyncio.run(Manager(cfg).startup())
    loaded = store.load_tasks()
    assert loaded[0].status == TaskState.PAUSED
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_interrupt_recovery.py -v`
Expected: FAIL

- [ ] **Step 3: 实现恢复逻辑**

在 `Manager.startup()` 末尾追加:
```python
        # 崩溃恢复: 旧的 running/queued 标记为 paused,保留上下文
        for t in self.store.load_tasks():
            if t.status in (TaskState.RUNNING, TaskState.QUEUED):
                t.status = TaskState.PAUSED
                self.store.save_task(t)
```
(需要 `from taskpanel.core.task import TaskState`。)

- [ ] **Step 4: 运行验证通过**

Run: `uv run pytest tests/test_interrupt_recovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/taskpanel/web/manager.py tests/test_interrupt_recovery.py
git commit -m "test: 长任务中断恢复(崩溃后 running→paused 保留上下文)"
```

---

### Task 18: 收尾 — 全量测试 + 代码自检

**Files:**
- 无新增;运行全量。

- [ ] **Step 1: 全量测试**

```bash
uv run pytest -q
```
Expected: 全部通过(含 config/task/llm/llm_raw/tools/agent_loop/store/worktree/ocr/api/ws/review_api/interrupt_recovery)。

- [ ] **Step 2: 手动验收清单**

- [ ] 面板里同时跑 ≥3 个 chat 任务,各输出互不串台。
- [ ] 新建一个 project 任务(worktree 开),并行另一个 project 任务,工作区互不污染。
- [ ] 任务运行中切走再切回,输出不中断。
- [ ] 停止后端再启动,任务出现在列表且状态为 paused,可 follow-up 续聊。
- [ ] 跑 `ocr review`,右栏出现 findings,可按 severity 筛选、折叠右栏。
- [ ] 后端断线重连(浏览器刷新),事件经 `since` 补齐不丢。

- [ ] **Step 3: Commit(如有残留改动)**

```bash
git add -A && git commit -m "chore: 全量测试通过 + 验收清单核对"
```

---

### Task 19: 共享记忆(可选,默认关)

**Files:**
- Create: `taskpanel/src/taskpanel/store/shared.py`
- Test: `taskpanel/tests/test_shared.py`

**Interfaces:**
- Produces:
  - `class SharedMemory:` 构造 `(base_dir: Path)`;数据目录 `base_dir/shared/`。
  - `def append(key: str, data: dict) -> None` — 追加写 `shared/<key>.jsonl`(键做安全化)。
  - `def read(key: str, from_offset: int = 0) -> list[dict]` — 返回 `{"offset": int, "data": dict}` 列表,支持游标续读。
  - 面板默认不启用:`Manager` 不实例化;任务间如需共享,后续接入。**并发语义**: 本面板所有任务运行于同一 Python 进程,用模块级 `threading.Lock` 保证追加原子性即足够;若未来跨进程,再换成文件锁(`fcntl.flock` / `msvcrt.locking`),见 spec §5。

- [ ] **Step 1: 写失败测试**

`tests/test_shared.py`:
```python
from taskpanel.store.shared import SharedMemory


def test_append_and_read(tmp_path):
    sm = SharedMemory(tmp_path)
    sm.append("ctx", {"task": "a"})
    sm.append("ctx", {"task": "b"})
    rows = sm.read("ctx")
    assert [r["data"]["task"] for r in rows] == ["a", "b"]


def test_read_from_offset(tmp_path):
    sm = SharedMemory(tmp_path)
    sm.append("ctx", {"n": 1})
    sm.append("ctx", {"n": 2})
    rows = sm.read("ctx", from_offset=1)
    assert rows[0]["offset"] == 2 and rows[0]["data"]["n"] == 2


def test_key_sanitized(tmp_path):
    sm = SharedMemory(tmp_path)
    sm.append("a/b:c", {"x": 1})
    assert (tmp_path / "shared" / "a_b_c.jsonl").exists()
```

- [ ] **Step 2: 运行验证失败**

Run: `uv run pytest tests/test_shared.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/taskpanel/store/shared.py`:
```python
from __future__ import annotations
import json
import threading
from pathlib import Path

_LOCK = threading.Lock()


class SharedMemory:
    def __init__(self, base_dir: Path):
        self.dir = Path(base_dir).expanduser() / "shared"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return self.dir / f"{safe}.jsonl"

    def append(self, key: str, data: dict) -> None:
        with _LOCK:
            with self._path(key).open("a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def read(self, key: str, from_offset: int = 0) -> list[dict]:
        p = self._path(key)
        if not p.exists():
            return []
        out = []
        for offset, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if offset > from_offset and line.strip():
                out.append({"offset": offset, "data": json.loads(line)})
        return out
```

- [ ] **Step 4: 运行验证通过**

Run: `uv run pytest tests/test_shared.py -v`
Expected: PASS(3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/taskpanel/store/shared.py tests/test_shared.py
git commit -m "feat: 共享记忆(append-only + 锁,默认不启用)"
```
