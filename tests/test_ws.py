import pytest
from fastapi.testclient import TestClient
from taskpanel.core.config import PanelConfig, LLMConfig
from taskpanel.web.server import create_app


@pytest.fixture
def client(tmp_path):
    cfg = PanelConfig(llm=LLMConfig(base_url="http://x", api_key="k", model="m"),
                      data_dir=tmp_path / "data")
    with TestClient(create_app(cfg)) as c:
        yield c


def test_ws_requires_token(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/tasks") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_ws_receives_events_and_replays(client):
    import time
    token = client.get("/api/bootstrap").json()["token"]
    h = {"X-Auth-Token": token}
    t = client.post("/api/tasks", json={"kind": "chat", "prompt": "hi"}, headers=h).json()
    # 等第一个任务产出存量事件(状态 running 写入 store),作为断线补齐的回放源
    for _ in range(50):
        if client.get(f"/api/tasks/{t['id']}/events", headers=h).json():
            break
        time.sleep(0.1)
    # 订阅后先回放存量事件(seq > last_event_id)
    with client.websocket_connect(f"/ws/tasks?token={token}") as ws:
        replayed = ws.receive_json()
        assert replayed["task_id"] == t["id"]
        # 实时推送: 订阅后建第二个任务,应收到其 status/queued 事件
        t2 = client.post("/api/tasks", json={"kind": "chat", "prompt": "hi2"}, headers=h).json()
        got = ws.receive_json()
        while got["task_id"] != t2["id"]:
            got = ws.receive_json()
        assert got["type"] == "status"
        assert got["task_id"] == t2["id"]
