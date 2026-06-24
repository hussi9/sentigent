"""Sub-agent role scaffolds — maker/checker + explorer/implementer/verifier (X1).

A bare loop runs one undifferentiated agent per step. Real autonomy benefits from
*separation of concerns* across laps: one role reads/understands, one role makes the
change, one role independently proves it. This module supplies tiny, pure scaffolds
the caller (or a loop) can use to tag steps with a role before feeding them into
`loop_driver.start(steps=...)`.

These are PROMPT PREFIXES, not executors — they shape what a lap is asked to do.
Keeping them as plain strings means they compose with `loop_driver`'s per-step text
without any coupling to it.
"""
from __future__ import annotations

# Role-prompt prefixes. Each describes, in one breath, the single job that role has
# this lap — so a fresh-context agent stays in its lane.
EXPLORER = (
    "[EXPLORER] Read and understand only. Do NOT change any files. Investigate the "
    "codebase and report what you found and what the change will require. STEP: "
)
IMPLEMENTER = (
    "[IMPLEMENTER] Make the change. Edit code to satisfy the step; keep it minimal "
    "and focused. Do not also write the verification — that is a separate role. STEP: "
)
VERIFIER = (
    "[VERIFIER] Prove it. Independently confirm the previous change is correct — run "
    "tests/typecheck/lint or add a check that fails if the work is wrong. STEP: "
)

_ROLES = {EXPLORER, IMPLEMENTER, VERIFIER}


def role_prompt(role: str, step_text: str) -> str:
    """Prepend a role prefix to a step's text.

    `role` must be one of the EXPLORER/IMPLEMENTER/VERIFIER constants. An unknown
    role raises ValueError — that's a programmer error (a typo'd constant), not a
    runtime condition, so it should fail loud and early.
    """
    if role not in _ROLES:
        raise ValueError(f"unknown role: {role!r} (use EXPLORER/IMPLEMENTER/VERIFIER)")
    return f"{role}{step_text}"


def maker_checker(step_text: str) -> list[str]:
    """Expand one step into a maker/checker pair: an IMPLEMENTER step then a VERIFIER
    step. This gives a plan independent make-vs-prove separation — the checker lap has
    a fresh context and only one job (prove the maker's work), so drift is caught.

    Scaffold usage: feed the result straight into `loop_driver.start`, e.g.
        steps = [s for st in raw_steps for s in maker_checker(st)]
        loop_driver.start(goal, steps)
    """
    return [role_prompt(IMPLEMENTER, step_text), role_prompt(VERIFIER, step_text)]
