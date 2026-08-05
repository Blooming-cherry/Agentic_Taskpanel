import pytest
from taskpanel.core.agent_loop import AgentLoop
from taskpanel.core.llm import LLMClient, LLMEvent
from taskpanel.core.task import Task, TaskState, make_task


class FakeClient(LLMClient):
    def __init__(self, script):
        """script: list[list[LLMEvent]] 每轮返回的事件列表"""
        self.script = script
        self.i = 0
    async def stream(self, messages, tools=None):
        for ev in self.script[self.i]:
            yield ev
        self.i += 1
    async def probe(self):
        return True


@pytest.mark.asyncio
async def test_run_no_tools_finalizes():
    task = make_task("chat", "hi")
    emitted = []
    loop = AgentLoop(task, FakeClient([[LLMEvent("text_delta", text="hello"),
                                        LLMEvent("done")]]),
                     tools=[], root=".", emit=emitted.append)
    state = await loop.run()
    assert state == TaskState.DONE
    assert task.messages[-1]["role"] == "assistant"
    assert any(e["type"] == "text_delta" for e in emitted)


@pytest.mark.asyncio
async def test_run_executes_tool_then_finalizes(tmp_path):
    from taskpanel.core.tools import BUILTIN_TOOLS
    task = make_task("project", "run pwd", cwd=str(tmp_path))
    emitted = []
    # 第一轮: 触发 bash;第二轮: 纯文本
    script = [
        [LLMEvent("tool_use", tool_use={"id": "t1", "name": "bash", "input": {"cmd": "pwd"}}),
         LLMEvent("done")],
        [LLMEvent("text_delta", text="done!"), LLMEvent("done")],
    ]
    loop = AgentLoop(task, FakeClient(script), tools=BUILTIN_TOOLS,
                     root=str(tmp_path), emit=emitted.append, max_rounds=3)
    state = await loop.run()
    assert state == TaskState.DONE
    assert any(e["type"] == "tool_result" for e in emitted)
    # 消息历史: user + assistant(tool_use) + user(tool_result) + assistant(最终)
    assert task.messages[1]["content"][0]["type"] == "tool_use"
    assert task.messages[2]["content"][0]["type"] == "tool_result"


@pytest.mark.asyncio
async def test_run_multi_tool_rounds_one_user_message(tmp_path):
    """一轮内 N 个 tool_use → 恰好 ONE 条 user(tool_result) 消息,含 N 个
    tool_result 块(Anthropic 分组,终审 Important 2a)。"""
    from taskpanel.core.tools import BUILTIN_TOOLS
    task = make_task("project", "multi", cwd=str(tmp_path))
    emitted = []
    script = [
        [LLMEvent("tool_use", tool_use={"id": "t1", "name": "bash", "input": {"cmd": "echo a"}}),
         LLMEvent("tool_use", tool_use={"id": "t2", "name": "bash", "input": {"cmd": "echo b"}}),
         LLMEvent("done")],
        [LLMEvent("text_delta", text="done"), LLMEvent("done")],
    ]
    loop = AgentLoop(task, FakeClient(script), tools=BUILTIN_TOOLS,
                     root=str(tmp_path), emit=emitted.append, max_rounds=3)
    state = await loop.run()
    assert state == TaskState.DONE
    # 用户消息: 初始 prompt + 恰好一条工具结果消息
    user_msgs = [m for m in task.messages if m["role"] == "user"]
    assert len(user_msgs) == 2, "多工具轮必须合并成一条 user 消息"
    blocks = user_msgs[-1]["content"]
    assert [b["type"] for b in blocks] == ["tool_result", "tool_result"]
    assert [b["tool_use_id"] for b in blocks] == ["t1", "t2"]
    assert all(b["tool_use_id"] == blocks[i]["tool_use_id"] for i, b in enumerate(blocks))


@pytest.mark.asyncio
async def test_run_text_plus_tool_use_same_round(tmp_path):
    """一轮内同时出现 text 与 tool_use → assistant 消息必须携带
    [text, tool_use] 两块,text 不得被丢弃(终审 Important 2b)。"""
    from taskpanel.core.tools import BUILTIN_TOOLS
    task = make_task("project", "t", cwd=str(tmp_path))
    emitted = []
    script = [
        [LLMEvent("text_delta", text="思考中…"),
         LLMEvent("tool_use", tool_use={"id": "t1", "name": "bash", "input": {"cmd": "pwd"}}),
         LLMEvent("done")],
        [LLMEvent("text_delta", text="完成"), LLMEvent("done")],
    ]
    loop = AgentLoop(task, FakeClient(script), tools=BUILTIN_TOOLS,
                     root=str(tmp_path), emit=emitted.append, max_rounds=3)
    state = await loop.run()
    assert state == TaskState.DONE
    assistants = [m for m in task.messages if m["role"] == "assistant"]
    assert len(assistants) == 2  # 工具轮 + 最终回答
    tool_round = assistants[0]
    assert [b["type"] for b in tool_round["content"]] == ["text", "tool_use"]
    assert tool_round["content"][0]["text"] == "思考中…", "同轮文本必须保留在历史里"


@pytest.mark.asyncio
async def test_cancel_pauses(tmp_path):
    task = make_task("chat", "hi")
    emitted = []

    class SlowClient(FakeClient):
        async def stream(self, messages, tools=None):
            yield LLMEvent("text_delta", text="a")
            await __import__("asyncio").sleep(0.05)
            yield LLMEvent("text_delta", text="b")
            yield LLMEvent("done")

    loop = AgentLoop(task, SlowClient([[]]), tools=[], root=".", emit=emitted.append)
    await __import__("asyncio").sleep(0.01)
    loop.cancel()
    state = await loop.run()
    assert state == TaskState.PAUSED
