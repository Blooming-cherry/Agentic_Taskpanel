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
