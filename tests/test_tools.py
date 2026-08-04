import pytest
from taskpanel.core.tools import execute_tool, BUILTIN_TOOLS
from taskpanel.core.task import make_task


@pytest.mark.asyncio
async def test_read_write_roundtrip(tmp_path):
    t = make_task("project", "x", cwd=str(tmp_path))
    out = await execute_tool("write_file",
                             {"path": "a.txt", "content": "hello"}, t, str(tmp_path))
    assert "ok" in out
    out2 = await execute_tool("read_file", {"path": "a.txt"}, t, str(tmp_path))
    assert "hello" in out2


@pytest.mark.asyncio
async def test_write_outside_root_rejected(tmp_path, tmp_path_factory):
    other = tmp_path_factory.mktemp("evil")
    t = make_task("project", "x", cwd=str(tmp_path))
    out = await execute_tool("write_file",
                             {"path": str(other / "pwn.txt"), "content": "x"}, t, str(tmp_path))
    assert "拒绝" in out


@pytest.mark.asyncio
async def test_bash_cwd_is_root(tmp_path):
    t = make_task("project", "x", cwd=str(tmp_path))
    out = await execute_tool("bash", {"cmd": "pwd"}, t, str(tmp_path))
    assert str(tmp_path) in out


def test_tools_schema():
    names = {t["name"] for t in BUILTIN_TOOLS}
    assert names == {"read_file", "write_file", "bash"}
