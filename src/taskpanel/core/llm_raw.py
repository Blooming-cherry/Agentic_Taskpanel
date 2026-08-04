from __future__ import annotations
import inspect
import json
import httpx

from taskpanel.core.config import LLMConfig
from taskpanel.core.llm import LLMClient, LLMEvent


class RawHTTPClient(LLMClient):
    """基于 httpx + SSE 流解析的兜底客户端。

    直接 POST {base_url}/v1/messages,按 SSE 行解析
    content_block_delta(text_delta / input_json_delta)、message_delta;
    结束后聚合 tool_use 块发出事件。若响应为完整消息对象(非流式/测试桩),
    同样能解析出 text 与 tool_use。
    """

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._http = httpx.AsyncClient(timeout=cfg.timeout)

    def _url(self) -> str:
        base = self.cfg.base_url.rstrip("/")
        return base + "/v1/messages" if not base.endswith("/messages") else base

    def _headers(self) -> dict:
        return {
            "x-api-key": self.cfg.api_key,
            "anthropic-version": "2023-06-01",
        }

    async def _post(self, url: str, json_body: dict) -> httpx.Response:
        """发 POST;兼容真异步 client 与同步测试桩。

        httpx.AsyncClient.post 返回协程需 await;测试里 monkeypatch 的
        同步桩直接返回响应对象,这里统一处理。
        """
        ret = self._http.post(url, json=json_body, headers=self._headers())
        return await ret if inspect.isawaitable(ret) else ret

    def _parse_line(self, line: str) -> dict | None:
        line = line.strip()
        if not line or line.startswith(":") or line == "[DONE]":
            return None
        if line.startswith("data:"):
            line = line[len("data:"):].strip()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def _finalize(self, block: dict) -> None:
        raw = "".join(block.pop("_parts", []))
        try:
            block["input"] = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            block["input"] = {"_raw": raw}

    async def stream(self, messages, tools=None):
        body = {"model": self.cfg.model, "max_tokens": 4096, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self._post(self._url(), body)
        if getattr(resp, "status_code", 200) >= 400:
            raise RuntimeError(f"RawHTTPClient: HTTP {resp.status_code}")
        tool_blocks: list[dict] = []
        current: dict | None = None  # 正在累积的 tool_use 块
        async for line in resp.aiter_lines():
            obj = self._parse_line(line)
            if obj is None:
                continue
            etype = obj.get("type")
            if etype == "content_block_delta":
                delta = obj.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield LLMEvent(type="text_delta", text=delta.get("text", ""))
                elif delta.get("type") == "input_json_delta":
                    if current is not None:
                        current["_parts"].append(delta.get("partial_json", ""))
            elif etype == "content_block_start":
                cb = obj.get("content_block", {})
                if cb.get("type") == "tool_use":
                    current = {"id": cb.get("id", ""), "name": cb.get("name", ""),
                               "_parts": []}
            elif etype == "content_block_stop":
                if current is not None:
                    self._finalize(current)
                    tool_blocks.append(current)
                    current = None
            elif etype == "message_delta":
                continue  # stop_reason 在此可选记录
            elif "content" in obj:
                # 完整消息对象(非流式代理 / 测试桩)
                for b in obj.get("content", []):
                    if b.get("type") == "text":
                        yield LLMEvent(type="text_delta", text=b.get("text", ""))
                    elif b.get("type") == "tool_use":
                        tool_blocks.append({
                            "id": b["id"], "name": b["name"],
                            "input": b.get("input", {})})
        for tb in tool_blocks:
            yield LLMEvent(type="tool_use", tool_use={
                "id": tb["id"], "name": tb["name"], "input": tb.get("input", {})})
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
        resp = await self._post(self._url(), body)
        data = resp.json()
        return any(b.get("type") == "tool_use" for b in data.get("content", []))


def pick_client(cfg: LLMConfig) -> tuple[LLMClient, str]:
    """返回 (client, kind);kind 为 "anthropic" 或 "raw"。

    SDK 可用时优先 SDK;否则回退 RawHTTPClient。SDK 首次运行时协议错
    的回退由调用方(build_client 之上)依据返回的 kind 决定。
    """
    from taskpanel.core.llm import HAS_ANTHROPIC, AnthropicSDKClient
    if HAS_ANTHROPIC:
        return AnthropicSDKClient(cfg), "anthropic"
    return RawHTTPClient(cfg), "raw"
