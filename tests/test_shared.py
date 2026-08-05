from taskpanel.store.shared import SharedMemory


def test_append_and_read(tmp_path):
    sm = SharedMemory(tmp_path)
    sm.append("ctx", {"task": "a"})
    sm.append("ctx", {"task": "b"})
    rows = sm.read("ctx")
    assert [r["data"]["task"] for r in rows] == ["a", "b"]


def test_read_from_offset(tmp_path):
    sm = SharedMemory(tmp_path)
    sm.append("ctx", {"n": 1})
    sm.append("ctx", {"n": 2})
    rows = sm.read("ctx", from_offset=1)
    assert rows[0]["offset"] == 2 and rows[0]["data"]["n"] == 2


def test_key_sanitized(tmp_path):
    sm = SharedMemory(tmp_path)
    sm.append("a/b:c", {"x": 1})
    assert (tmp_path / "shared" / "a_b_c.jsonl").exists()
