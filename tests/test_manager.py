import asyncio

from taskpanel.core.config import PanelConfig, LLMConfig
from taskpanel.core.llm import LLMEvent
from taskpanel.core.task import TaskState, make_task
from taskpanel.web.manager import Manager


def _cfg(tmp_path, max_retries=2):
    return PanelConfig(
        llm=LLMConfig(base_url="http://localhost:9999/v1", api_key="k",
                      model="m", max_retries=max_retries),
        data_dir=tmp_path / "data",
        max_parallel=1,
        worktree_auto_cleanup=False,
    )


async def _mgr(tmp_path):
    mgr = Manager(_cfg(tmp_path))
    await mgr.startup()
    return mgr


async def test_dispatch_root_error_releases_sem_and_broadcasts(tmp_path):
    """入口 _root_for 抛错:信号量释放、任务 ERROR、广播收到 error 事件。"""
    mgr = await _mgr(tmp_path)

    async def boom(task):
        raise RuntimeError("root boom")

    mgr._root_for = boom  # type: ignore[method-assign]
    task = make_task("chat", "hi")
    mgr.store.save_task(task)
    q = mgr.subscribe()

    await mgr._dispatch(task)

    assert task.status == TaskState.ERROR
    assert task.error == "root boom"
    assert not mgr._sem.locked()
    assert task.id not in mgr._loops
    evs = []
    while not q.empty():
        evs.append(q.get_nowait())
    assert any(e.get("type") == "error" for e in evs)
    assert evs[-1]["task_id"] == task.id


async def test_dispatch_build_client_error_marks_error(tmp_path, monkeypatch):
    """入口 build_client 抛错同样被捕获:ERROR + 信号量释放。"""
    mgr = await _mgr(tmp_path)

    def boom(cfg):
        raise RuntimeError("client boom")

    monkeypatch.setattr("taskpanel.web.manager.build_client", boom)
    task = make_task("chat", "hi")
    mgr.store.save_task(task)

    await mgr._dispatch(task)

    assert task.status == TaskState.ERROR
    assert task.error == "client boom"
    assert not mgr._sem.locked()
    assert task.id not in mgr._loops


class FailingAfterFirstClient:
    """第一次 stream 产出 tool_use 并正常结束(让 AgentLoop 写入完整半轮:
    assistant tool_use + user tool_result);之后的每次 stream 直接抛错,
    用于验证重试前消息历史被回滚,第二次 attempt 看到干净的上下文。"""

    def __init__(self):
        self.stream_calls = 0
        self.seen = []  # 每次 stream 调用收到的 messages 的 role 序列

    async def probe(self):
        return False

    async def stream(self, messages, tools=None):
        self.stream_calls += 1
        self.seen.append([m.get("role") for m in messages])
        if self.stream_calls == 1:
            yield LLMEvent(type="tool_use", tool_use={
                "id": "t1", "name": "read_file",
                "input": {"path": "__nope__.txt"}})
            yield LLMEvent(type="done")
            return
        raise RuntimeError("stream boom")


async def _fast_sleep(*args, **kwargs):
    return None


async def test_dispatch_retry_rolls_back_dirty_messages(tmp_path, monkeypatch):
    """第一次 run() 写入脏半轮消息后抛错:第二次 attempt 输入已回滚,
    最终消息历史不含脏消息,信号量照常释放。"""
    mgr = Manager(_cfg(tmp_path, max_retries=2))
    await mgr.startup()
    client = FailingAfterFirstClient()
    monkeypatch.setattr("taskpanel.web.manager.build_client", lambda _cfg: client)
    monkeypatch.setattr("taskpanel.web.manager.asyncio.sleep", _fast_sleep)
    task = make_task("chat", "hi")
    mgr.store.save_task(task)

    await mgr._dispatch(task)

    # attempt0: stream#1 干净(只有 user),stream#2 带脏半轮;
    # attempt1(第二次):stream#3 应已回滚,只有 user,不含 assistant/tool 脏消息。
    assert client.stream_calls == 3
    assert client.seen[0] == ["user"]
    assert client.seen[1] == ["user", "assistant", "user"]
    assert client.seen[2] == ["user"]
    assert task.status == TaskState.ERROR
    assert not any(m.get("role") == "assistant" for m in task.messages)
    assert not any(c.get("type") == "tool_result"
                   for m in task.messages for c in m.get("content", []))
    assert not mgr._sem.locked()
    assert task.id not in mgr._loops
