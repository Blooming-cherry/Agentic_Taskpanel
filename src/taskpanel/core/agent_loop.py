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
        res = self.emit(event)
        if hasattr(res, "__await__"):
            await res

    async def run(self) -> TaskState:
        if not self.task.messages:
            self.task.messages.append(
                {"role": "user",
                 "content": [{"type": "text", "text": self.task.prompt}]})
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
