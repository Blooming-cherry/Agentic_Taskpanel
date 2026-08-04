from __future__ import annotations
import asyncio
from fastapi import FastAPI, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from taskpanel.core.config import PanelConfig
from taskpanel.web.manager import Manager


class CreateBody(BaseModel):
    kind: str = "chat"
    prompt: str
    cwd: str | None = None
    use_worktree: bool = False


class FollowBody(BaseModel):
    text: str


def create_app(cfg: PanelConfig) -> FastAPI:
    app = FastAPI()
    mgr = Manager(cfg)

    @app.on_event("startup")
    async def _startup():
        await mgr.startup()

    def auth(x_auth_token: str = Header(default="")):
        if x_auth_token != mgr.auth_token():
            raise HTTPException(401, "invalid token")

    @app.get("/api/bootstrap")
    async def bootstrap():
        return {"token": mgr.auth_token()}

    @app.get("/api/tasks", dependencies=[Depends(auth)])
    async def list_tasks():
        return [t.__dict__ | {"status": t.status.value} for t in mgr.list_tasks()]

    @app.post("/api/tasks", dependencies=[Depends(auth)])
    async def create_task(body: CreateBody):
        t = await mgr.create_task(body.kind, body.prompt, body.cwd, body.use_worktree)
        return t.__dict__ | {"status": t.status.value}

    @app.get("/api/tasks/{task_id}", dependencies=[Depends(auth)])
    async def get_task(task_id: str):
        t = mgr.get(task_id)
        if not t:
            raise HTTPException(404, "task not found")
        return t.__dict__ | {"status": t.status.value, "messages": t.messages}

    @app.post("/api/tasks/{task_id}/messages", dependencies=[Depends(auth)])
    async def follow_up(task_id: str, body: FollowBody):
        try:
            return await mgr.follow_up(task_id, body.text)
        except KeyError:
            raise HTTPException(404, "task not found")

    @app.post("/api/tasks/{task_id}/stop", dependencies=[Depends(auth)])
    async def stop(task_id: str):
        await mgr.stop(task_id)
        return {"ok": True}

    @app.delete("/api/tasks/{task_id}", dependencies=[Depends(auth)])
    async def delete(task_id: str):
        await mgr.delete(task_id)
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/review", dependencies=[Depends(auth)])
    async def run_review(task_id: str, background: str = ""):
        try:
            return await mgr.run_review(task_id, background)
        except KeyError:
            raise HTTPException(404, "task not found")

    @app.get("/api/tasks/{task_id}/review", dependencies=[Depends(auth)])
    async def get_review(task_id: str):
        return mgr.get_review(task_id)

    @app.get("/api/tasks/{task_id}/context", dependencies=[Depends(auth)])
    async def get_context(task_id: str, path: str, line: int, context: int = 8):
        try:
            return await mgr.get_context(task_id, path, line, context)
        except (KeyError, FileNotFoundError):
            raise HTTPException(404, "not found")

    @app.get("/api/tasks/{task_id}/events", dependencies=[Depends(auth)])
    async def events(task_id: str, since: int = Query(0)):
        return mgr.events_since(task_id, since)

    @app.websocket("/ws/tasks")
    async def ws(ws: WebSocket, token: str = Query(""),
                 last_event_id: int = Query(0)):
        if token != mgr.auth_token():
            await ws.close(code=4401)
            return
        await ws.accept()
        # 先订阅再回放: 消除 store 读取与 subscribe 之间追加事件
        # (既不回放也不实时推送)的丢失窗口。
        q = mgr.subscribe()
        try:
            max_seen = last_event_id
            # 断线补齐: 补发所有任务 seq > last_event_id 的事件
            for task in mgr.list_tasks():
                for ev in mgr.events_since(task.id, last_event_id):
                    await ws.send_json(ev)
                    max_seen = max(max_seen, ev["seq"])
            while True:
                event = await q.get()
                if event["seq"] <= max_seen:
                    continue
                await ws.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            mgr.unsubscribe(q)

    import os
    static = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static):
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app
