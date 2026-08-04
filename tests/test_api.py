import pytest
from fastapi.testclient import TestClient
from taskpanel.core.config import PanelConfig, LLMConfig
from taskpanel.web.server import create_app
from taskpanel.web.manager import Manager


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = PanelConfig(
        llm=LLMConfig(base_url="http://localhost:9999/v1", api_key="k", model="m"),
        data_dir=tmp_path / "data", bind_port=1)
    app = create_app(cfg)
    with TestClient(app) as c:
        yield c


def test_bootstrap_returns_token(client):
    r = client.get("/api/bootstrap")
    assert r.status_code == 200
    assert "token" in r.json()


def test_auth_required(client):
    r = client.get("/api/tasks")
    assert r.status_code == 401


def test_create_list_delete(client):
    token = client.get("/api/bootstrap").json()["token"]
    h = {"X-Auth-Token": token}
    r = client.post("/api/tasks", json={"kind": "chat", "prompt": "你好"},
                    headers=h)
    assert r.status_code == 200
    task_id = r.json()["id"]
    lst = client.get("/api/tasks", headers=h).json()
    assert any(t["id"] == task_id for t in lst)
    r = client.delete(f"/api/tasks/{task_id}", headers=h)
    assert r.status_code == 200


def test_delete_traversal_does_not_destroy_data(tmp_path):
    """DELETE /api/tasks/.. 等非法 id 必须 404,且 data_dir(.auth_token/tasks)
    完好无损(破坏性路径穿越,终审 Critical 1)。"""
    cfg = PanelConfig(
        llm=LLMConfig(base_url="http://localhost:9999/v1", api_key="k", model="m"),
        data_dir=tmp_path / "data", bind_port=1)
    with TestClient(create_app(cfg)) as c:
        token = c.get("/api/bootstrap").json()["token"]
        h = {"X-Auth-Token": token}
        r = c.post("/api/tasks", json={"kind": "chat", "prompt": "x"}, headers=h)
        assert r.status_code == 200
        tid = r.json()["id"]

        # 用 %2e%2e 绕过 httpx 的 ".." 归一化,真正命中 DELETE /api/tasks/{id}
        # 路由,让 manager.delete("..") 被调用(旧实现会把 data_dir 整个删掉)。
        r = c.delete("/api/tasks/%2e%2e", headers=h)
        assert r.status_code == 404

        # data_dir 完好
        assert (cfg.data_dir / ".auth_token").exists()
        assert (cfg.data_dir / "tasks").is_dir()
        assert (cfg.data_dir / "tasks" / tid / "meta.json").exists()
        lst = c.get("/api/tasks", headers=h).json()
        assert any(t["id"] == tid for t in lst)
