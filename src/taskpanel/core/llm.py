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
            timeout=self.cfg.timeout,
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
