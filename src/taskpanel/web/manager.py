from __future__ import annotations
import asyncio
import secrets
from pathlib import Path

from taskpanel.core.config import PanelConfig
from taskpanel.core.task import Task, TaskState, make_task
from taskpanel.core.llm import build_client, LLMClient, AnthropicSDKClient
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
        # 信号量在 _dispatch 内获取并释放:create_task 不再持有,消除
        # acquire 之后、spawn 之前被取消导致的永不释放泄漏窗口。
        asyncio.create_task(self._dispatch(task))
        return task

    def _tools_for(self, task: Task) -> list[dict]:
        if task.kind != "project":
            return chat_tools()
        key = (self.cfg.llm.base_url, self.cfg.llm.model)
        if key not in self._probe_cache:
            return chat_tools()  # 探测未完成,先用纯文本
        return BUILTIN_TOOLS if self._probe_cache[key] else chat_tools()

    async def _dispatch(self, task: Task):
        # 信号量在 _dispatch 内获取/释放:入口抛错(如 _root_for /
        # build_client)或任务中途被取消时,finally 仍会释放,不留泄漏窗口。
        if self._sem is not None:
            await self._sem.acquire()
        try:
            root = await self._root_for(task)
            client = build_client(self.cfg.llm)
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
                snapshot = list(task.messages)
                try:
                    await loop.run()
                    self.store.save_task(task)
                    return
                except Exception as e:  # noqa: BLE001 协议/网络错误
                    # 回滚本次尝试写入的半轮消息(如 tool_use 缺 tool_result),
                    # 避免下一次 attempt 带着脏上下文重跑。
                    task.messages[:] = snapshot
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
            full = self.store.append_event(task.id, {"type": "error", "error": str(e)})
            await self.broadcast(full)
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
            loop = AgentLoop(task, client, self._tools_for(task), task.cwd or ".",
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
