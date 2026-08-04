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
