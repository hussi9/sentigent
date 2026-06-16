"""Org guardrail packs — data-driven, org-enforceable safety for the loop.

A guardrail PACK is a YAML file an org authors, shares, and enforces. Each pack holds
rules; each rule matches a step (or command) and yields an action: block / approve / warn.
Rules are DATA, not code — an org adds guardrails without touching Python.

In the loop, this is the per-lap safety invariant: before the driver dispatches a step,
it checks the step against the enabled packs. A `block`/`approve` hit stops the lap for
human sign-off (the loop won't drive a dangerous step off a cliff); `warn` proceeds with
a note. Opt-in (orgs enable it); never fires unless turned on.

Load order is the org's choice (enforcement list); precedence: block > approve > warn.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:  # fail-soft: no yaml → no guardrails (don't crash the loop)
    yaml = None

_DEFAULT_DIR = Path(__file__).parent.parent.parent / "guardrails"
_PRIORITY = {"block": 3, "approve": 2, "warn": 1, "allow": 0}


@dataclass
class Rule:
    id: str
    pack: str
    action: str          # block | approve | warn
    severity: str
    message: str
    pattern: re.Pattern
    excludes: re.Pattern | None = None


@dataclass
class Decision:
    decision: str        # block | approve | warn | allow
    rule_id: str = ""
    pack: str = ""
    severity: str = ""
    message: str = ""

    @property
    def stops_lap(self) -> bool:
        """block/approve require a human before the step proceeds."""
        return self.decision in ("block", "approve")


def load_packs(pack_dir: Path | str | None = None, enabled: list[str] | None = None) -> list[Rule]:
    """Load rules from every pack YAML in pack_dir (or only `enabled` pack ids)."""
    if yaml is None:
        return []
    d = Path(pack_dir or _DEFAULT_DIR)
    if not d.exists():
        return []
    rules: list[Rule] = []
    for f in sorted(d.glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text()) or {}
        except Exception:
            continue
        pack = str(doc.get("pack", f.stem))
        if enabled and pack not in enabled:
            continue
        for r in doc.get("rules", []) or []:
            pat = r.get("pattern")
            if not pat:
                continue
            try:
                cre = re.compile(pat, re.IGNORECASE)
                exc = re.compile(r["excludes"], re.IGNORECASE) if r.get("excludes") else None
            except re.error:
                continue
            rules.append(Rule(
                id=str(r.get("id", "?")), pack=pack,
                action=str(r.get("action", "approve")).lower(),
                severity=str(r.get("severity", "medium")),
                message=str(r.get("message", "")),
                pattern=cre, excludes=exc,
            ))
    return rules


def evaluate(text: str, rules: list[Rule]) -> Decision:
    """Highest-priority rule that matches `text`. allow if none."""
    text = text or ""
    best: Decision | None = None
    for r in rules:
        if r.excludes and r.excludes.search(text):
            continue
        if r.pattern.search(text):
            d = Decision(r.action, r.id, r.pack, r.severity, r.message)
            if best is None or _PRIORITY.get(d.decision, 0) > _PRIORITY.get(best.decision, 0):
                best = d
    return best or Decision("allow")
