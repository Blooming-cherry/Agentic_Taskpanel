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


@pytest.mark.asyncio
async def test_raw_stream_parses_sse_events(monkeypatch):
    def _sse(obj):
        return "data: " + json.dumps(obj)

    lines = [
        _sse({"type": "content_block_start", "index": 0,
              "content_block": {"type": "text", "text": ""}}),
        _sse({"type": "content_block_delta", "index": 0,
              "delta": {"type": "text_delta", "text": "hi"}}),
        _sse({"type": "content_block_stop", "index": 0}),
        _sse({"type": "content_block_start", "index": 1,
              "content_block": {"type": "tool_use", "id": "t1",
                                "name": "bash", "input": {}}}),
        _sse({"type": "content_block_delta", "index": 1,
              "delta": {"type": "input_json_delta",
                        "partial_json": json.dumps({"cmd": "pwd"})}}),
        _sse({"type": "content_block_stop", "index": 1}),
        _sse({"type": "message_delta",
              "delta": {"stop_reason": "tool_use", "stop_sequence": None}}),
    ]

    def fake_post(*a, **kw):
        class R:
            status_code = 200
            async def aiter_lines(self):
                for line in lines:
                    yield line
        return R()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = RawHTTPClient(LLMConfig(base_url="http://x/v1", api_key="k", model="m"))
    events = [e async for e in client.stream([{"role": "user", "content": "hi"}], [])]
    texts = [e.text for e in events if e.type == "text_delta"]
    tools = [e.tool_use for e in events if e.type == "tool_use"]
    assert texts == ["hi"]
    assert tools[0]["id"] == "t1"
    assert tools[0]["name"] == "bash"
    assert tools[0]["input"] == {"cmd": "pwd"}
    assert events[-1].type == "done"
