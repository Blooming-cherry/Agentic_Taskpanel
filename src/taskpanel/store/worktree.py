from __future__ import annotations
import subprocess
import uuid
from pathlib import Path


class WorktreeManager:
    def __init__(self, base_dir: Path | None = None,
                 auto_cleanup: bool = True, max_retained: int = 5):
        self.base_dir = Path(base_dir or Path.home() / ".taskpanel" / "worktrees").expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.auto_cleanup = auto_cleanup
        self.max_retained = max_retained

    def create(self, repo: str) -> str:
        name = uuid.uuid4().hex[:8]
        dest = self.base_dir / name
        subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", str(dest)],
                       check=True, capture_output=True)
        return str(dest)

    def _repo_of(self, path: str) -> str:
        gitfile = Path(path) / ".git"
        if gitfile.is_file():
            for line in gitfile.read_text(encoding="utf-8").splitlines():
                if line.startswith("gitdir:"):
                    d = Path(line.split(":", 1)[1].strip())
                    # gitdir 形如 <repo>/.git/worktrees/<name>
                    return str(d.resolve().parent.parent.parent)
        return str(Path(path).parent)

    def remove(self, path: str) -> None:
        repo = self._repo_of(path)
        subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", path],
                       check=False, capture_output=True)

    def cleanup(self) -> int:
        """删除超出 max_retained 的 worktree。调用方应先移走仍活跃的任务,
        否则按创建时间保留最近 max_retained 个。"""
        if not self.base_dir.exists():
            return 0
        wts = sorted(self.base_dir.iterdir(), key=lambda p: p.stat().st_mtime)
        removed = 0
        for wt in wts[:max(0, len(wts) - self.max_retained)]:
            self.remove(str(wt))
            removed += 1
        return removed
