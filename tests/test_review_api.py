import pytest
from fastapi.testclient import TestClient
from taskpanel.core.config import PanelConfig, LLMConfig
from taskpanel.web.server import create_app
from taskpanel.web.manager import Manager


class FakeOCR:
    async def run_review(self, cwd, background="", extra=None):
        return {"ok": True, "findings": [{"file": "a.py", "line": 3,
                                          "severity": "high", "text": "NPE risk"}],
                "raw": "", "stderr": ""}


def _cfg(tmp_path):
    return PanelConfig(llm=LLMConfig(base_url="http://x", api_key="k", model="m"),
                       data_dir=tmp_path / "data")


@pytest.fixture
async def mgr_task(tmp_path):
    """直接构造 Manager + 注入 FakeOCR + 建一个 cwd=tmp_path 的任务。"""
    mgr = Manager(_cfg(tmp_path))
    await mgr.startup()
    mgr.ocr = FakeOCR()
    t = await mgr.create_task("project", "review", cwd=str(tmp_path))
    yield mgr, t, tmp_path


async def test_review_endpoint_returns_findings(mgr_task):
    mgr, t, _ = mgr_task
    await mgr.run_review(t.id)
    r = mgr.get_review(t.id)
    assert r["findings"][0]["text"] == "NPE risk"


# ---- get_context: 锚点行 math 与切片边界 ----

async def test_get_context_anchor_math(mgr_task):
    mgr, t, tmp_path = mgr_task
    (tmp_path / "a.py").write_text(
        "\n".join(f"line{i}" for i in range(1, 21)) + "\n", encoding="utf-8")
    body = await mgr.get_context(t.id, "a.py", 5, 2)
    assert body["start"] == 3
    assert body["lines"] == ["line3", "line4", "line5", "line6", "line7"]


async def test_get_context_boundary_top(mgr_task):
    mgr, t, tmp_path = mgr_task
    (tmp_path / "a.py").write_text(
        "\n".join(f"line{i}" for i in range(1, 21)) + "\n", encoding="utf-8")
    body = await mgr.get_context(t.id, "a.py", 1, 2)
    assert body["start"] == 1
    assert body["lines"] == ["line1", "line2", "line3"]


async def test_get_context_boundary_bottom(mgr_task):
    mgr, t, tmp_path = mgr_task
    (tmp_path / "a.py").write_text(
        "\n".join(f"line{i}" for i in range(1, 21)) + "\n", encoding="utf-8")
    body = await mgr.get_context(t.id, "a.py", 20, 2)
    assert body["start"] == 18
    assert body["lines"] == ["line18", "line19", "line20"]


# ---- get_context: 路径穿越 containment 防护 ----

async def test_get_context_rejects_traversal(mgr_task):
    """.. 穿越必须被拒: 不修实现时能读到 root 之外的 secret 文件,修复后抛 404。"""
    mgr, t, tmp_path = mgr_task
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("classified", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        await mgr.get_context(t.id, "../secret.txt", 1)


async def test_get_context_rejects_absolute_path(mgr_task):
    """绝对路径直接拒绝,即使指向 root 内部文件。"""
    mgr, t, tmp_path = mgr_task
    f = tmp_path / "a.py"
    f.write_text("x\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        await mgr.get_context(t.id, str(f.resolve()), 1)


async def test_get_context_directory_raises_404(mgr_task):
    """读目录(IsADirectoryError)必须映射为 FileNotFoundError → 404,而非 500。"""
    mgr, t, _ = mgr_task
    with pytest.raises(FileNotFoundError):
        await mgr.get_context(t.id, ".", 1)


# ---- HTTP 端点: 404 行为 ----

async def test_context_http_traversal_404(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path.parent / "secret.txt").write_text("classified", encoding="utf-8")
    with TestClient(create_app(cfg)) as c:
        token = c.get("/api/bootstrap").json()["token"]
        h = {"X-Auth-Token": token}
        r = c.post("/api/tasks", json={"kind": "chat", "prompt": "x",
                                       "cwd": str(tmp_path)}, headers=h)
        assert r.status_code == 200
        tid = r.json()["id"]
        r = c.get(f"/api/tasks/{tid}/context",
                  params={"path": "../secret.txt", "line": 1}, headers=h)
        assert r.status_code == 404


async def test_context_http_returns_lines(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "a.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    with TestClient(create_app(cfg)) as c:
        token = c.get("/api/bootstrap").json()["token"]
        h = {"X-Auth-Token": token}
        r = c.post("/api/tasks", json={"kind": "chat", "prompt": "x",
                                       "cwd": str(tmp_path)}, headers=h)
        tid = r.json()["id"]
        r = c.get(f"/api/tasks/{tid}/context",
                  params={"path": "a.py", "line": 2}, headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["start"] == 1
        assert body["lines"] == ["line1", "line2", "line3"]


async def test_context_http_unknown_task_404(tmp_path):
    cfg = _cfg(tmp_path)
    with TestClient(create_app(cfg)) as c:
        token = c.get("/api/bootstrap").json()["token"]
        h = {"X-Auth-Token": token}
        r = c.get("/api/tasks/nope/context",
                  params={"path": "a.py", "line": 1}, headers=h)
        assert r.status_code == 404
