"""Chain circuit-breaker (D-021): borderline detection, the consecutive-streak trip, and a real
operate() run that pauses after too many borderline auto-applies instead of letting them compound."""
from __future__ import annotations

import os
import tempfile

import pytest

from sentigent.operator.chain_guard import ChainGuard, is_borderline
from sentigent.memory.store import MemoryStore
from sentigent.operator.operate import operate
from sentigent.operator.plan import Plan, Step
from sentigent.operator.escalation import COPILOT
from sentigent.operator.resolver import Resolution, APPROVE


# -- pure unit: is_borderline -------------------------------------------------

@pytest.mark.parametrize("conf,thr,expected", [
    (0.75, 0.72, True),    # just over the floor → borderline
    (0.72, 0.72, True),    # exactly at the floor → borderline (it only just cleared)
    (0.90, 0.72, False),   # comfortably over → confident, not borderline
    (0.70, 0.72, False),   # under the floor → wouldn't auto-apply at all
    (0.82, 0.72, False),   # at floor+margin → out of the borderline band
])
def test_is_borderline(conf, thr, expected):
    assert is_borderline(conf, thr, margin=0.10) is expected


# -- ChainGuard streak / trip / reset ----------------------------------------

def test_guard_trips_after_consecutive_borderline():
    g = ChainGuard(max_consecutive=3, margin=0.10)
    assert g.record(step=1, confidence=0.74, threshold=0.72) is False  # streak 1
    assert g.record(step=2, confidence=0.75, threshold=0.72) is False  # streak 2
    assert g.record(step=3, confidence=0.73, threshold=0.72) is True   # streak 3 -> TRIP
    assert len(g.trail) == 3


def test_confident_call_resets_the_streak():
    g = ChainGuard(max_consecutive=2)
    assert g.record(step=1, confidence=0.74, threshold=0.72) is False  # borderline, streak 1
    assert g.record(step=2, confidence=0.99, threshold=0.72) is False  # confident -> reset
    assert g.record(step=3, confidence=0.74, threshold=0.72) is False  # borderline, streak 1 again
    assert g.streak == 1
    assert len(g.trail) == 2  # the two borderline calls are still on the trail


# -- integration: operate() pauses when the chain trips ----------------------

class _ApprovingResolver:
    """Clone that keeps auto-approving at a BORDERLINE confidence (just over the 0.72 floor)."""
    def __init__(self, confidence: float):
        self.confidence = confidence
    def resolve(self, _blocker) -> Resolution:
        return Resolution(APPROVE, self.confidence, "borderline approve", source="llm")


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as d:
        yield MemoryStore(agent_id="t-chain", org_id="t", db_path=os.path.join(d, "m.db"))


def test_operate_trips_breaker_on_borderline_chain(store):
    # 5-step plan, dry-run. COPILOT asks on every step → the injected clone is consulted each time
    # and auto-approves at 0.75 (borderline vs the 0.75 default floor for the copilot category).
    # After 3 in a row the breaker must trip: run pauses instead of letting the chain compound.
    steps = [Step(idx=i, description=f"do thing {i}") for i in range(1, 6)]
    res = operate(store, Plan(goal="borderline chain", steps=steps),
                  autonomy=COPILOT, execute=False,
                  resolver=_ApprovingResolver(0.75), chain_break_after=3)

    assert res.status == "waiting"                      # the run paused instead of finishing
    assert len(res.borderline) >= 3                     # the reviewable trail captured them
    assert res.open_escalation_id is not None           # a human checkpoint was filed
    # only the first 2 borderline steps auto-completed before the trip on the 3rd
    assert sum(1 for o in res.outcomes if o.status == "done") == 2


def test_operate_no_trip_when_confident(store):
    # Same setup but the clone is confident (0.95, not borderline) → no trip, run completes.
    steps = [Step(idx=i, description=f"do thing {i}") for i in range(1, 6)]
    res = operate(store, Plan(goal="confident chain", steps=steps),
                  autonomy=COPILOT, execute=False,
                  resolver=_ApprovingResolver(0.95), chain_break_after=3)
    assert res.status == "done"
    assert res.borderline == []                         # nothing borderline
    assert res.steps_done == 5
