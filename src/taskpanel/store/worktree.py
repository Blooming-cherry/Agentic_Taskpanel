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

    def cleanup(self, active: set[str] | None = None) -> int:
        """删除 stale 且超出 max_retained 的 worktree,返回清理数。

        active: 仍被任务引用的 worktree 路径集合(由调用方把活跃任务与
        keep_worktree 任务的 worktree 并进来),集合内的路径永不删除。
        只对未被引用的 stale worktree 按创建时间保留最近 max_retained 个,
        其余删除——避免清理把正在使用的 worktree 删掉。
        """
        if not self.base_dir.exists():
            return 0
        protected = {str(Path(p).expanduser().resolve()) for p in (active or set())}
        stale = [p for p in self.base_dir.iterdir()
                 if str(p.expanduser().resolve()) not in protected]
        stale.sort(key=lambda p: p.stat().st_mtime)
        removed = 0
        for wt in stale[:max(0, len(stale) - self.max_retained)]:
            self.remove(str(wt))
            removed += 1
        return removed
