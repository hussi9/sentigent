"""PlanIngest (B1) — accept a plan in any form, turn it into executable steps.

Accepts the markdown task-list format you already produce (writing-plans /
checkbox lists), a numbered list, or one task per line. No LLM needed for the
common case; a fuzzy one-line goal can be decomposed later (B2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Step:
    idx: int
    description: str
    done: bool = False           # was the checkbox already ticked
    domain: str = "global"       # inferred coarse domain (deploy/db/frontend/test/...)
    raw: str = ""
    phase: str = ""              # phase label from the nearest preceding "## ..." heading
    done_criteria: dict = field(default_factory=dict)  # machine-checkable acceptance criteria


@dataclass
class Plan:
    goal: str
    steps: list[Step] = field(default_factory=list)
    source: str = "markdown"

    @property
    def pending(self) -> list[Step]:
        return [s for s in self.steps if not s.done]


# checkbox: "- [ ] do thing" / "- [x] done thing"; numbered: "1. do thing"; or bare bullet.
_CHECKBOX = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<text>.+?)\s*$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s*(?P<text>.+?)\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(?P<text>.+?)\s*$")
_HEADING = re.compile(r"^\s*#+\s*(?P<text>.+?)\s*$")

# coarse domain inference — keep cheap; the gate does the real reasoning.
_DOMAIN_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(deploy|vercel|eas|cloud run|release|ship)\b", re.I), "deploy"),
    (re.compile(r"\b(migrat|schema|supabase|sql|table|database|\bdb\b)\b", re.I), "db"),
    (re.compile(r"\b(test|vitest|pytest|jest|spec|coverage)\b", re.I), "test"),
    (re.compile(r"\b(review|refactor|lint|typecheck|tsc)\b", re.I), "review"),
    (re.compile(r"\b(component|ui|css|tailwind|page|route|frontend)\b", re.I), "frontend"),
    (re.compile(r"\b(secret|api key|token|auth|rls|security)\b", re.I), "security"),
]


def _infer_domain(text: str) -> str:
    for pat, dom in _DOMAIN_HINTS:
        if pat.search(text):
            return dom
    return "global"


def _parse_criteria(text: str) -> tuple[str, dict]:
    """Split a task line into (description, done_criteria).

    Criteria follow the description after `||` separators and map to Verifier keys:
      verify:/test: <cmd> -> test_cmd ; build: <cmd> -> build_cmd ;
      files: a,b -> files_exist ; grep: <pat> @ <path> -> grep ; diff -> diff_nonempty.
    Unknown segments are ignored (kept out of the description).
    """
    parts = [p.strip() for p in text.split("||")]
    description = parts[0].strip()
    crit: dict = {}
    for seg in parts[1:]:
        if not seg:
            continue
        low = seg.lower()
        if low.startswith(("verify:", "test:")):
            crit["test_cmd"] = seg.split(":", 1)[1].strip()
        elif low.startswith("build:"):
            crit["build_cmd"] = seg.split(":", 1)[1].strip()
        elif low.startswith("files:"):
            files = [f.strip() for f in seg.split(":", 1)[1].split(",") if f.strip()]
            if files:
                crit["files_exist"] = files
        elif low.startswith("grep:"):
            body = seg.split(":", 1)[1].strip()
            if "@" in body:
                pat, path = body.rsplit("@", 1)
                crit["grep"] = {"pattern": pat.strip(), "path": path.strip()}
        elif low == "diff":
            crit["diff_nonempty"] = True
    return description, crit


def parse_plan(text: str, goal: str | None = None) -> Plan:
    """Parse markdown / list text into a Plan. The first '# ...' heading becomes the
    goal (if not given); subsequent headings ('## ...') set the current phase for the
    tasks that follow. Checkbox state is honored (ticked = done). Each task line may
    carry `|| key: value` done-criteria."""
    steps: list[Step] = []
    inferred_goal = goal
    current_phase = ""
    idx = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        h = _HEADING.match(line)
        if h:
            htext = h.group("text").strip()
            if inferred_goal is None:
                inferred_goal = htext      # first heading = goal
            else:
                current_phase = htext      # later headings = phase label
            continue
        m = _CHECKBOX.match(line)
        if m:
            idx += 1
            desc, crit = _parse_criteria(m.group("text").strip())
            steps.append(Step(
                idx=idx, description=desc, done=m.group("mark").lower() == "x",
                domain=_infer_domain(desc), raw=line.strip(),
                phase=current_phase, done_criteria=crit,
            ))
            continue
        m = _NUMBERED.match(line) or _BULLET.match(line)
        if m:
            idx += 1
            desc, crit = _parse_criteria(m.group("text").strip())
            steps.append(Step(
                idx=idx, description=desc, domain=_infer_domain(desc),
                raw=line.strip(), phase=current_phase, done_criteria=crit,
            ))
    return Plan(goal=inferred_goal or "(untitled plan)", steps=steps)


def parse_plan_file(path: str, goal: str | None = None) -> Plan:
    p = Plan(goal=goal or "(missing)", steps=[])
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return p
    plan = parse_plan(text, goal=goal)
    plan.source = path
    return plan
