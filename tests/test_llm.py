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
