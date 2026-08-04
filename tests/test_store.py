import json
from pathlib import Path
from taskpanel.core.task import make_task
from taskpanel.store.store import TaskStore


def test_save_and_load(tmp_path):
    store = TaskStore(tmp_path)
    t = make_task("chat", "hello world", cwd=None)
    store.save_task(t)
    loaded = store.load_tasks()
    assert len(loaded) == 1 and loaded[0].id == t.id and loaded[0].title == "hello world"


def test_messages_persist(tmp_path):
    store = TaskStore(tmp_path)
    t = make_task("chat", "hi")
    t.messages.append({"role": "user", "content": [{"type": "text", "text": "hi"}]})
    store.save_task(t)
    assert store.load_messages(t.id) == t.messages


def test_events_seq_monotonic(tmp_path):
    store = TaskStore(tmp_path)
    t = make_task("chat", "hi")
    store.save_task(t)
    e1 = store.append_event(t.id, {"type": "text_delta", "text": "a"})
    e2 = store.append_event(t.id, {"type": "text_delta", "text": "b"})
    assert e1["seq"] == 1 and e2["seq"] == 2
    since = store.events_since(t.id, 1)
    assert [e["seq"] for e in since] == [2]


def test_delete(tmp_path):
    store = TaskStore(tmp_path)
    t = make_task("chat", "hi")
    store.save_task(t)
    store.delete_task(t.id)
    assert store.load_tasks() == []
