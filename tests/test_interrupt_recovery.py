import json
from pathlib import Path
from taskpanel.core.task import TaskState
from taskpanel.store.store import TaskStore


def test_startup_marks_stale_running_as_paused(tmp_path):
    store = TaskStore(tmp_path)
    t = __import__("taskpanel.core.task", fromlist=["make_task"]).make_task("chat", "hi")
    t.status = TaskState.RUNNING
    store.save_task(t)
    # 模拟 Manager.startup 的恢复逻辑
    from taskpanel.web.manager import Manager
    from taskpanel.core.config import PanelConfig, LLMConfig
    import asyncio
    cfg = PanelConfig(llm=LLMConfig(), data_dir=tmp_path)
    asyncio.run(Manager(cfg).startup())
    loaded = store.load_tasks()
    assert loaded[0].status == TaskState.PAUSED
