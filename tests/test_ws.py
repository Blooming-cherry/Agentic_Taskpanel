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
    # 先订阅再回放: last_event_id=0 低于存量 seq,存量事件应被回放
    with client.websocket_connect(f"/ws/tasks?token={token}") as ws:
        replayed = ws.receive_json()
        assert replayed["task_id"] == t["id"]
        seen = {(replayed["task_id"], replayed["seq"])}
        # 实时推送: 订阅后建第二个任务。它的第 1 条 status 事件(全局 seq
        # 大于回放水位 max_seen)必须被收到,不能被跨任务水位误删。
        t2 = client.post("/api/tasks", json={"kind": "chat", "prompt": "hi2"}, headers=h).json()
        got = ws.receive_json()
        while got["task_id"] != t2["id"]:
            assert (got["task_id"], got["seq"]) not in seen, "事件被重复推送"
            seen.add((got["task_id"], got["seq"]))
            got = ws.receive_json()
        # 收到的第一条 t2 事件即为其首个 status 事件;逐条去重,不得重复投递
        assert got["type"] == "status"
        assert got["task_id"] == t2["id"]
        assert (got["task_id"], got["seq"]) not in seen, "事件被重复推送"
