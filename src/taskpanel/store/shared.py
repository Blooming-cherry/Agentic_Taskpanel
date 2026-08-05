from __future__ import annotations
import json
import threading
from pathlib import Path

_LOCK = threading.Lock()


class SharedMemory:
    def __init__(self, base_dir: Path):
        self.dir = Path(base_dir).expanduser() / "shared"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return self.dir / f"{safe}.jsonl"

    def append(self, key: str, data: dict) -> None:
        with _LOCK:
            with self._path(key).open("a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def read(self, key: str, from_offset: int = 0) -> list[dict]:
        p = self._path(key)
        if not p.exists():
            return []
        out = []
        for offset, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if offset > from_offset and line.strip():
                out.append({"offset": offset, "data": json.loads(line)})
        return out
