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
