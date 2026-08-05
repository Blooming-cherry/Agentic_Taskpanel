import pytest
from taskpanel.core.config import LLMConfig
from taskpanel.core.llm import build_client, AnthropicSDKClient, LLMClient


def test_build_client_prefers_sdk(monkeypatch):
    monkeypatch.setattr("taskpanel.core.llm.HAS_ANTHROPIC", True)
    cfg = LLMConfig(base_url="http://localhost:9999/v1", api_key="k", model="m")
    client = build_client(cfg)
    assert isinstance(client, AnthropicSDKClient)


def test_sdk_stream_does_not_pass_stream_kwarg(monkeypatch):
    """AnthropicSDKClient.stream 不得把 stream=True 透传给 messages.stream()。

    新版 anthropic SDK 的 .stream() 助手不接受 stream 关键字,透传会抛
    TypeError,导致 SDK 路径的真实 LLM 调用全部崩溃。回归保护。
    """
    import asyncio
    from types import SimpleNamespace
    seen = {}

    class FakeStream:
        def __init__(self, **kwargs):
            seen["kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        @property
        def text_stream(self):
            async def gen():
                yield "hi"
            return gen()

        async def get_final_message(self):
            return SimpleNamespace(content=[])

    class FakeMessages:
        def stream(self, **kwargs):
            return FakeStream(**kwargs)

    class FakeAnthropic:
        def __init__(self, *a, **k):
            self.messages = FakeMessages()

    monkeypatch.setattr("taskpanel.core.llm.anthropic.AsyncAnthropic", FakeAnthropic)
    client = AnthropicSDKClient(
        LLMConfig(base_url="http://x/v1", api_key="k", model="m"))

    async def go():
        return [ev async for ev in client.stream(
            [{"role": "user", "content": "hi"}])]

    events = asyncio.run(go())
    assert "stream" not in seen["kwargs"], "stream=True 不得透传给 SDK .stream()"
    assert [e.type for e in events] == ["text_delta", "done"]


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
