from __future__ import annotations
import json
import threading
from pathlib import Path

from taskpanel.core.task import Task, TaskState


class TaskStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).expanduser()
        self.tasks_dir = self.data_dir / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        # 事件 seq 全局单调递增(跨任务),断线补齐与前端单水位线都依赖它
        self._seq_lock = threading.Lock()
        self._seq_path = self.data_dir / "seq"

    def _dir(self, task_id: str) -> Path:
        d = self.tasks_dir / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_task(self, task: Task) -> None:
        d = self._dir(task.id)
        meta = {
            "id": task.id, "kind": task.kind, "prompt": task.prompt,
            "cwd": task.cwd, "use_worktree": task.use_worktree,
            "title": task.title, "status": task.status.value,
            "token_count": task.token_count, "created_at": task.created_at,
            "updated_at": task.updated_at, "error": task.error,
            "worktree": task.worktree, "keep_worktree": task.keep_worktree,
        }
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        msg_path = d / "messages.jsonl"
        existing = self.load_messages(task.id)
        new_msgs = task.messages[len(existing):]
        with msg_path.open("a", encoding="utf-8") as f:
            for m in new_msgs:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    def append_event(self, task_id: str, event: dict) -> dict:
        d = self._dir(task_id)
        ev_path = d / "events.jsonl"
        # 全局 seq: 跨任务单调递增,由 data_dir/seq 文件在锁内推进
        with self._seq_lock:
            n = int(self._seq_path.read_text()) if self._seq_path.exists() else 0
            n += 1
            self._seq_path.write_text(str(n))
            seq = n
        full = {"seq": seq, "task_id": task_id, **event}
        with ev_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(full, ensure_ascii=False) + "\n")
        return full

    def get_or_none(self, task_id: str) -> Task | None:
        meta = self.tasks_dir / task_id / "meta.json"
        if not meta.exists():
            return None
        return self._task_from_meta(json.loads(meta.read_text(encoding="utf-8")))

    def load_tasks(self) -> list[Task]:
        tasks = []
        for d in self.tasks_dir.iterdir():
            meta = d / "meta.json"
            if meta.exists():
                tasks.append(self._task_from_meta(json.loads(meta.read_text(encoding="utf-8"))))
        return sorted(tasks, key=lambda t: t.created_at)

    def _task_from_meta(self, m: dict) -> Task:
        return Task(
            id=m["id"], kind=m["kind"], prompt=m["prompt"], cwd=m.get("cwd"),
            use_worktree=m.get("use_worktree", False), title=m["title"],
            status=TaskState(m.get("status", "queued")),
            token_count=m.get("token_count", 0),
            created_at=m.get("created_at", ""), updated_at=m.get("updated_at", ""),
            error=m.get("error"), worktree=m.get("worktree"),
            keep_worktree=m.get("keep_worktree", False),
        )

    def load_messages(self, task_id: str) -> list[dict]:
        p = self._dir(task_id) / "messages.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]

    def events_since(self, task_id: str, seq: int) -> list[dict]:
        p = self._dir(task_id) / "events.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            ev = json.loads(line)
            if ev["seq"] > seq:
                out.append(ev)
        return out

    def delete_task(self, task_id: str) -> None:
        import shutil
        shutil.rmtree(self.tasks_dir / task_id, ignore_errors=True)
