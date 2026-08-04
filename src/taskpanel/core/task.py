from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class Task:
    id: str
    kind: str
    prompt: str
    cwd: str | None
    use_worktree: bool
    title: str
    status: TaskState
    messages: list[dict] = field(default_factory=list)
    token_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    error: str | None = None
    worktree: str | None = None
    keep_worktree: bool = False

    def touch(self):
        self.updated_at = datetime.now(timezone.utc).isoformat()


def make_task(kind: str, prompt: str, cwd: str | None = None,
              use_worktree: bool = False) -> Task:
    now = datetime.now(timezone.utc).isoformat()
    return Task(
        id=uuid.uuid4().hex[:8],
        kind=kind,
        prompt=prompt,
        cwd=cwd,
        use_worktree=use_worktree,
        title=prompt[:30],
        status=TaskState.QUEUED,
        created_at=now,
        updated_at=now,
    )
