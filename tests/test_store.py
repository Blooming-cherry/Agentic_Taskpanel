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


def test_load_restores_messages(tmp_path):
    """重启后读回任务,持久化的对话历史必须恢复到 Task.messages,
    follow-up 才能带上下文续聊(中断恢复验收项)。"""
    store = TaskStore(tmp_path)
    t = make_task("chat", "hi")
    t.messages = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "old reply"}]},
    ]
    store.save_task(t)
    assert store.load_tasks()[0].messages == t.messages
    assert store.get_or_none(t.id).messages == t.messages
    # 再次 save 不得把已有消息重复追加
    store.save_task(store.get_or_none(t.id))
    assert len(store.load_messages(t.id)) == 2


def test_events_seq_monotonic(tmp_path):
    store = TaskStore(tmp_path)
    t = make_task("chat", "hi")
    store.save_task(t)
    e1 = store.append_event(t.id, {"type": "text_delta", "text": "a"})
    e2 = store.append_event(t.id, {"type": "text_delta", "text": "b"})
    assert e1["seq"] == 1 and e2["seq"] == 2
    since = store.events_since(t.id, 1)
    assert [e["seq"] for e in since] == [2]


def test_events_seq_global_monotonic_across_tasks(tmp_path):
    store = TaskStore(tmp_path)
    a = make_task("chat", "a")
    b = make_task("chat", "b")
    store.save_task(a)
    store.save_task(b)
    assert store.append_event(a.id, {"type": "text_delta", "text": "a1"})["seq"] == 1
    assert store.append_event(a.id, {"type": "text_delta", "text": "a2"})["seq"] == 2
    assert store.append_event(b.id, {"type": "text_delta", "text": "b1"})["seq"] == 3


def test_delete(tmp_path):
    store = TaskStore(tmp_path)
    t = make_task("chat", "hi")
    store.save_task(t)
    assert store.delete_task(t.id) is True
    assert store.load_tasks() == []


def test_delete_rejects_bad_ids(tmp_path):
    """delete_task 必须拒绝 "" / ".." / 未知 id: 返回 False 且绝不 rmtree
    data_dir 或 tasks 目录(破坏性路径穿越,终审 Critical 1)。"""
    store = TaskStore(tmp_path)
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("x", encoding="utf-8")
    t = make_task("chat", "hi")
    store.save_task(t)

    assert store.delete_task("") is False
    assert store.delete_task("..") is False
    assert store.delete_task("nope") is False

    # data_dir 完好: 哨兵文件与任务目录都在,任务仍可加载
    assert sentinel.exists()
    assert (tmp_path / "tasks").is_dir()
    assert (tmp_path / "tasks" / t.id / "meta.json").exists()
    assert [x.id for x in store.load_tasks()] == [t.id]

    # 正常 id 删除仍然工作
    assert store.delete_task(t.id) is True
    assert store.load_tasks() == []
