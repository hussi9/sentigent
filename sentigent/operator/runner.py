"""OperatorRunner (C1) + OutputObserver (C3) — drive Claude Code AS you.

The worker is `claude -p` headless (it's always present inside Claude Code, so no
extra dependency — locked substrate decision). For one step the runner builds a
prompt, spawns `claude -p --output-format stream-json`, parses the event stream
(tool calls, final text, token usage), and hands a structured TurnResult back to
the operate() loop for judging.

Dry-run is the default: no subprocess, no changes — a synthetic turn so the whole
loop can run safely and observably before it's trusted to execute for real.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TurnResult:
    ok: bool
    text: str                                # final assistant text / "done" claim
    tool_uses: list[dict] = field(default_factory=list)  # [{name, input_summary}]
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""
    dry_run: bool = False

    @property
    def actions_text(self) -> str:
        """A flat string of what the turn proposed — fed to the risk floor."""
        parts = [self.text]
        for t in self.tool_uses:
            parts.append(f"{t.get('name','')}: {t.get('input_summary','')}")
        return "\n".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "text": self.text[:500], "tool_uses": self.tool_uses,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "error": self.error, "dry_run": self.dry_run,
        }


def _summarize_input(inp) -> str:
    """A short, safe one-line summary of a tool_use input (for risk + audit)."""
    if isinstance(inp, dict):
        for k in ("command", "file_path", "path", "url", "content", "query"):
            if k in inp and inp[k]:
                return f"{k}={str(inp[k])[:160]}"
        return json.dumps(inp)[:160]
    return str(inp)[:160]


def parse_stream_json(raw: str) -> TurnResult:
    """OutputObserver — parse `claude -p --output-format stream-json` JSONL output.
    Defensive: tolerant of version drift; salvages text/tools/usage best-effort."""
    text_parts: list[str] = []
    tool_uses: list[dict] = []
    in_tok = out_tok = 0
    result_text = ""
    saw_any = False

    for line in raw.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        saw_any = True
        etype = ev.get("type")

        if etype == "assistant":
            msg = ev.get("message", {})
            for block in msg.get("content", []) or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text"):
                    text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    tool_uses.append({
                        "name": block.get("name", ""),
                        "input_summary": _summarize_input(block.get("input")),
                    })
            usage = msg.get("usage") or {}
            in_tok += int(usage.get("input_tokens", 0) or 0)
            out_tok += int(usage.get("output_tokens", 0) or 0)

        elif etype == "result":
            result_text = ev.get("result", "") or ""
            usage = ev.get("usage") or {}
            if usage:
                in_tok = int(usage.get("input_tokens", in_tok) or in_tok)
                out_tok = int(usage.get("output_tokens", out_tok) or out_tok)

    final = result_text or "\n".join(text_parts)
    return TurnResult(
        ok=saw_any, text=final.strip(), tool_uses=tool_uses,
        input_tokens=in_tok, output_tokens=out_tok,
        error="" if saw_any else "no parseable stream-json events",
    )


class OperatorRunner:
    def __init__(self, model: Optional[str] = None, timeout: float = 600.0,
                 dry_run: bool = True, permission_mode: str = "default"):
        self.model = model
        self.timeout = timeout
        self.dry_run = dry_run
        self.permission_mode = permission_mode

    def drive(self, prompt: str, *, system: str = "",
              workdir: Optional[str] = None) -> TurnResult:
        """Drive one worker turn. Dry-run returns a synthetic result; real mode
        spawns `claude -p`. Always fail-soft (ok=False on any failure)."""
        if self.dry_run:
            first = (prompt.strip().splitlines() or [""])[0][:120]
            est = max(1, len(prompt) // 4)
            return TurnResult(
                ok=True, text=f"[dry-run] would work on: {first}",
                input_tokens=est, output_tokens=est // 2, dry_run=True,
            )

        claude = shutil.which("claude")
        if not claude:
            return TurnResult(False, "", error="claude binary not on PATH")

        cmd = [claude, "-p", prompt, "--output-format", "stream-json", "--verbose"]
        if system:
            cmd += ["--append-system-prompt", system]
        if self.model:
            cmd += ["--model", self.model]
        if self.permission_mode:
            cmd += ["--permission-mode", self.permission_mode]
        try:
            proc = subprocess.run(
                cmd, cwd=workdir or os.getcwd(), capture_output=True, text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return TurnResult(False, "", error=f"claude -p timed out after {self.timeout}s")
        except Exception as exc:
            return TurnResult(False, "", error=str(exc))

        res = parse_stream_json(proc.stdout)
        if not res.ok and proc.returncode != 0:
            res.error = (proc.stderr or res.error)[:300]
        return res
