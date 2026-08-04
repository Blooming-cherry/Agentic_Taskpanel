from __future__ import annotations
import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from taskpanel.core.task import Task

BUILTIN_TOOLS = [
    {"name": "read_file", "description": "读取文件内容",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"}},
                      "required": ["path"]}},
    {"name": "write_file", "description": "写入文件(仅限工作区)",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "bash", "description": "在工作区目录运行 shell 命令",
     "input_schema": {"type": "object",
                      "properties": {"cmd": {"type": "string"}},
                      "required": ["cmd"]}},
]


def chat_tools() -> list[dict]:
    return []


def _in_root(path: str, root: str) -> bool:
    p = Path(path).expanduser().resolve()
    r = Path(root).expanduser().resolve()
    return p.is_relative_to(r)


def _resolve(path: str, root: str) -> str:
    """相对路径以 root 为基准解析, 保证解析结果落在工作区内。"""
    r = Path(root).expanduser().resolve()
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = r / p
    return str(p.resolve())


def _bash_env() -> tuple[dict | None, str | None]:
    """Windows 的 cmd 没有 pwd 内建, PATH 上的 Git pwd.exe 输出 MSYS 路径(/tmp/...);
    生成原生的 pwd.cmd 垫片并前置到 PATH, 使 `pwd` 输出 Windows 形式 CWD。"""
    if os.name != "nt":
        return None, None
    shim_dir = tempfile.mkdtemp(prefix="taskpanel-pwd-")
    (Path(shim_dir) / "pwd.cmd").write_text("@echo %CD%\r\n", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = shim_dir + os.pathsep + env.get("PATH", "")
    return env, shim_dir


async def execute_tool(name: str, args: dict, task: Task, root: str) -> str:
    root = str(Path(root).expanduser().resolve())
    try:
        if name == "read_file":
            p = _resolve(args["path"], root)
            if not _in_root(p, root):
                return "拒绝:路径在工作区之外"
            return Path(p).read_text(encoding="utf-8", errors="replace")
        if name == "write_file":
            p = _resolve(args["path"], root)
            if not _in_root(p, root):
                return "拒绝:路径在工作区之外"
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            Path(p).write_text(args["content"], encoding="utf-8")
            return "ok"
        if name == "bash":
            env, shim_dir = _bash_env()
            try:
                proc = await asyncio.create_subprocess_shell(
                    args["cmd"], cwd=root, env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE)
                out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
                return (out.decode("utf-8", "replace")
                        + err.decode("utf-8", "replace")).strip() or "(空输出)"
            finally:
                if shim_dir:
                    shutil.rmtree(shim_dir, ignore_errors=True)
        return f"未知工具 {name}"
    except Exception as e:  # noqa: BLE001
        return f"工具执行出错: {e}"
