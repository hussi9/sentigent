"""GoalDoD — the goal-level `/goal` stop primitive for the Loop.

Step `done_criteria` (Verifier) answers "is this STEP done?". GoalDoD answers the
question that lets the factory decide it's finished with no human in the seat: "is
the WHOLE objective satisfied?". Hard, verifiable checks run first (tests/build/
files/grep, via the existing Verifier — conservative: unrunnable check = fail).
An optional small-model pass ("given this, is the objective met?") can act as a
secondary gate when the goal has a natural-language acceptance bar.

Conservative by design (mirrors Verifier): no criteria → NOT satisfied. A false
"goal done" silently ends the run with work unfinished, which is worse than one
extra lap.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sentigent.intelligence import local_llm
from sentigent.operator.verifier import Verifier

_SYSTEM = (
    "You judge whether a software objective is fully met. Be strict: only say done "
    "if the objective is genuinely complete. Output STRICT JSON."
)
_SCHEMA = """Return ONLY this JSON:
{"done": true|false, "reason": "<one sentence>"}"""


@dataclass
class DoDResult:
    satisfied: bool
    reason: str

    def to_dict(self) -> dict:
        return {"satisfied": self.satisfied, "reason": self.reason}


class GoalDoD:
    """Goal-level definition-of-done. `criteria` uses the same shape as step
    done_criteria (test_cmd/build_cmd/files_exist/grep/diff_nonempty), plus an
    optional `objective` string for the model pass."""

    def __init__(self, goal: str, criteria: Optional[dict] = None,
                 model: Optional[str] = None):
        self.goal = goal
        self.criteria = criteria or {}
        self.model = model

    def satisfied(self, repo_path: str) -> DoDResult:
        """Return whether the whole goal is done in `repo_path`. Never raises."""
        hard = {k: v for k, v in self.criteria.items() if k != "objective"}
        objective = self.criteria.get("objective")

        if not hard and not objective:
            return DoDResult(False, "no goal done-criteria — can't confirm done")

        # Hard checks first. If any requested check fails, the goal is not done.
        if hard:
            try:
                vres = Verifier(repo_path).verify(hard)
            except Exception as e:  # noqa: BLE001 — fail-soft, treat as not-done
                return DoDResult(False, f"verifier error: {e}")
            if not vres.done:
                return DoDResult(False, vres.reason)

        # Optional model pass: only a SECONDARY gate (hard checks already passed).
        if objective and local_llm.llm_available():
            raw = local_llm.generate_json(
                f"{_SCHEMA}\n\nOBJECTIVE:\n{objective}\n\nGOAL:\n{self.goal}\n",
                model=self.model, system=_SYSTEM,
            )
            if isinstance(raw, dict) and "done" in raw:
                if not bool(raw.get("done")):
                    return DoDResult(False, str(raw.get("reason", "objective not met")))

        return DoDResult(True, "goal done-criteria satisfied")
