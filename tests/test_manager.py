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


class EchoStreamClient:
    """stream 记录收到的 messages,直接 done(不产文本/工具),便于断言 follow-up
    是否带着持久化的历史上下文。"""

    def __init__(self):
        self.seen_messages = []

    async def probe(self):
        return False

    async def stream(self, messages, tools=None):
        self.seen_messages.append(messages)
        yield LLMEvent(type="done")


async def test_replay_events_globally_sorted(tmp_path):
    """断线补齐的回放必须按全局 seq 升序。

    事件 seq 跨任务全局单调,但按任务逐个回放时,后建任务的低 seq 事件会排在
    先建任务的高 seq 事件之后,导致回放流全局倒序;客户端以全局水位去重会把
    倒序的低 seq 事件误判为重复而丢弃(补齐丢事件)。回归保护。
    """
    mgr = await _mgr(tmp_path)
    a = make_task("chat", "a")
    b = make_task("chat", "b")
    mgr.store.save_task(a)
    mgr.store.save_task(b)
    mgr.store.append_event(a.id, {"type": "status", "status": "running"})  # seq 1
    mgr.store.append_event(b.id, {"type": "status", "status": "running"})  # seq 2
    mgr.store.append_event(a.id, {"type": "text_delta", "text": "x"})      # seq 3
    mgr.store.append_event(b.id, {"type": "error", "error": "boom"})       # seq 4
    mgr.store.append_event(a.id, {"type": "error", "error": "boom"})       # seq 5

    replay = mgr.replay_events(0)
    seqs = [e["seq"] for e in replay]
    assert seqs == [1, 2, 3, 4, 5], "跨任务回放必须全局 seq 升序"
    assert all(seqs[i] < seqs[i + 1] for i in range(len(seqs) - 1))

    # 断线水位: 只补 > last_event_id 的事件,同样保持升序
    replay2 = mgr.replay_events(2)
    assert [e["seq"] for e in replay2] == [3, 4, 5]


async def _wait_loop_done(mgr, task_id, timeout=5.0):
    t0 = asyncio.get_running_loop().time()
    while task_id in mgr._loops:
        if asyncio.get_running_loop().time() - t0 > timeout:
            raise AssertionError("follow-up loop did not finish")
        await asyncio.sleep(0.02)


async def test_follow_up_resumes_paused_with_context(tmp_path, monkeypatch):
    """重启后 paused 任务 follow-up: 持久化历史必须恢复进 Task.messages,
    并作为上下文传给下一次 stream(中断恢复『可续聊』的回归保护)。"""
    client = EchoStreamClient()
    monkeypatch.setattr("taskpanel.web.manager.build_client", lambda _cfg: client)
    mgr = await _mgr(tmp_path)
    task = make_task("chat", "origin")
    task.status = TaskState.PAUSED
    task.messages = [
        {"role": "user", "content": [{"type": "text", "text": "origin"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "old reply"}]},
    ]
    mgr.store.save_task(task)
    reloaded = mgr.get(task.id)  # 模拟重启后从 store 读回
    assert len(reloaded.messages) == 2, "重启后历史必须被恢复"

    r = await mgr.follow_up(reloaded.id, "follow")
    assert r["status"] == "queued"
    await _wait_loop_done(mgr, reloaded.id)

    msgs = client.seen_messages[-1]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    texts = [c["text"] for m in msgs for c in m["content"] if c.get("type") == "text"]
    assert "old reply" in texts and "follow" in texts


async def test_follow_up_error_marks_error_and_broadcasts(tmp_path, monkeypatch):
    """follow-up 后台执行抛错: 必须落 ERROR + 广播 error 事件(而非未捕获的
    background task 异常),与 _dispatch 行为一致。"""
    class BoomClient:
        async def probe(self):
            return False

        async def stream(self, messages, tools=None):
            raise RuntimeError("follow boom")
            yield LLMEvent(type="done")  # noqa: B018 保持 async gen 形态,迭代时才抛错

    monkeypatch.setattr("taskpanel.web.manager.build_client", lambda _cfg: BoomClient())
    mgr = await _mgr(tmp_path)
    task = make_task("chat", "hi")
    task.status = TaskState.PAUSED
    task.messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    mgr.store.save_task(task)
    q = mgr.subscribe()

    r = await mgr.follow_up(task.id, "go")
    assert r["status"] == "queued"
    await _wait_loop_done(mgr, task.id)

    # follow_up 会从 store 重新读回任务对象,断言须基于重取后的实例
    reloaded = mgr.get(task.id)
    assert reloaded.id not in mgr._loops
    assert reloaded.status == TaskState.ERROR
    assert "follow boom" in reloaded.error
    evs = []
    while not q.empty():
        evs.append(q.get_nowait())
    assert any(e.get("type") == "error" and e.get("task_id") == task.id for e in evs)
