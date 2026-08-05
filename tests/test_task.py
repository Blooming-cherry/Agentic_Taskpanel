from taskpanel.core.task import Task, TaskState, make_task


def test_make_task_fields():
    t = make_task("chat", "帮我整理这个问题的要点，稍微长一点的标题", cwd=None)
    assert t.kind == "chat"
    assert t.status == TaskState.QUEUED
    assert t.title == "帮我整理这个问题的要点，稍微长一点的标题"
    assert len(t.id) == 8
    assert t.messages == []


def test_state_values():
    assert TaskState.RUNNING.value == "running"
    assert TaskState.PAUSED.value == "paused"
