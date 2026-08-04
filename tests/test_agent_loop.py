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
