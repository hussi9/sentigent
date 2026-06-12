"""Shift-left test gate — populate the verification the Verifier already runs (D-006).

Anthropic / OpenAI / AWS all converge on the same rule: don't mark a step "done" until the
project's own tests pass. Sentigent's `Verifier` already runs a `test_cmd` done-criterion
(verifier.py) — the missing piece is *supplying* it without the planner hand-writing the command.

`detect_test_command` discovers the project's test command from its manifests; `ensure_test_criterion`
folds it into a step's done-criteria so the Verifier enforces a green run. Detection is
conservative and **read-only** — it inspects files and runs nothing. The Verifier does the running.
"""
from __future__ import annotations

import json
import os
from typing import Optional


def detect_test_command(cwd: str) -> Optional[str]:
    """Best-effort project test command, or None if undetectable. Read-only.

    Order: Node (package.json scripts.test) → Python → Rust → Go. Conservative: skips the
    npm placeholder ('no test specified') so we never gate on a guaranteed-failing default."""
    # Node
    pkg = os.path.join(cwd, "package.json")
    if os.path.isfile(pkg):
        try:
            with open(pkg, "r", encoding="utf-8") as fh:
                scripts = (json.load(fh) or {}).get("scripts") or {}
            test = str(scripts.get("test", ""))
            if test and "no test specified" not in test.lower():
                return "npm test --silent"
        except Exception:
            pass
    # Python
    for marker in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg"):
        if os.path.isfile(os.path.join(cwd, marker)):
            return "pytest -q"
    if os.path.isdir(os.path.join(cwd, "tests")):
        return "pytest -q"
    # Rust / Go
    if os.path.isfile(os.path.join(cwd, "Cargo.toml")):
        return "cargo test"
    if os.path.isfile(os.path.join(cwd, "go.mod")):
        return "go test ./..."
    return None


def ensure_test_criterion(criteria: Optional[dict], cwd: str) -> dict:
    """Return criteria with a detected `test_cmd` added when one isn't already set. Pure;
    never overrides an explicit test_cmd. The Verifier runs whatever is returned here."""
    out = dict(criteria or {})
    if "test_cmd" not in out:
        cmd = detect_test_command(cwd)
        if cmd:
            out["test_cmd"] = cmd
    return out
