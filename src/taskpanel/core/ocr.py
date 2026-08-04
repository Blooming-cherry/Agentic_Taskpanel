from __future__ import annotations
import asyncio
import json


class OcrRunner:
    def __init__(self, timeout: int = 1800, llm_env: dict | None = None):
        self.timeout = timeout
        self.llm_env = llm_env or {}

    def _env(self):
        env = dict(self.llm_env)
        if env.get("OCR_LLM_URL") and env.get("OCR_LLM_TOKEN"):
            env.setdefault("OCR_USE_ANTHROPIC", "true")
        return env

    async def _run(self, cwd: str, args: list[str]) -> dict:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**__import__("os").environ, **self._env()})
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"ok": False, "raw": "", "stderr": "OCR 超时被终止", "findings": []}
        stdout = out.decode("utf-8", "replace")
        stderr = err.decode("utf-8", "replace")
        findings = []
        for line in reversed(stdout.strip().splitlines()):
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    findings = data.get("findings", data.get("comments", []))
                    break
            except json.JSONDecodeError:
                continue
        return {"ok": proc.returncode == 0 and bool(findings),
                "raw": stdout, "stderr": stderr, "findings": findings}

    async def llm_test(self) -> bool:
        r = await self._run(".", ["ocr", "llm", "test"])
        return r["ok"]

    async def run_review(self, cwd: str, background: str = "",
                         extra: list[str] | None = None) -> dict:
        args = ["ocr", "review", "--audience", "agent"]
        if background:
            args += ["--background", background]
        args += extra or []
        return await self._run(cwd, args)

    async def scan(self, cwd: str, path: str = "") -> dict:
        args = ["ocr", "scan"] + ([path] if path else [])
        return await self._run(cwd, args)
