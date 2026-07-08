"""End-to-end (Task 8): a real phased plan with Definition-of-Done flows through
parse_plan -> operate() in dry-run, emitting phase events and persisting criteria.
Proves the whole Make-Fly-Work chain on the upgraded code (no claude -p, no worktree)."""
import json
import sqlite3

from sentigent.operator.plan import parse_plan
from sentigent.operator.operate import operate
from sentigent.memory.store import MemoryStore


PLAN_MD = """# Fly self-test

## Phase 1: read
- [ ] Summarize what plan.py does || diff

## Phase 2: verify
- [ ] Confirm the summary is non-empty || diff
"""


def _latest_plan_id(store):
    conn = sqlite3.connect(store.db_path)
    try:
        return conn.execute("SELECT id FROM plans ORDER BY id DESC LIMIT 1").fetchone()[0]
    finally:
        conn.close()


def _events(store, run_id, etype):
    out = []
    for e in store.get_run_events(run_id):
        if e.get("type") == etype:
            payload = e.get("payload")
            out.append(json.loads(payload) if isinstance(payload, str) else (payload or {}))
    return out


def test_phased_plan_runs_end_to_end(tmp_path, monkeypatch):
    # Hermetic: stub the local-LLM boundary so the gate's verdict is
    # deterministic on machines without a local model (CI). Without this the
    # heuristic fallback is low-confidence and the decider correctly escalates,
    # turning the run status into "waiting" instead of "done".
    from sentigent.operator import gate as gate_mod
    monkeypatch.setattr(gate_mod.local_llm, "llm_available", lambda *a, **k: True)
    monkeypatch.setattr(
        gate_mod.local_llm, "generate_json",
        lambda *a, **k: {"decision": "continue", "confidence": 0.95,
                         "reason": "stubbed verdict for hermetic e2e", "correction": ""},
    )

    store = MemoryStore(agent_id="t-fly", org_id="t", db_path=tmp_path / "fly.db")
    plan = parse_plan(PLAN_MD)

    # Parser: goal + two phases + per-task criteria.
    assert plan.goal == "Fly self-test"
    assert [s.phase for s in plan.steps] == ["Phase 1: read", "Phase 2: verify"]
    assert all(s.done_criteria == {"diff_nonempty": True} for s in plan.steps)

    # Operate (dry-run): every step completes, nothing escalates.
    res = operate(store, plan, execute=False)
    assert res.status == "done"
    assert res.steps_done == 2
    assert res.asks == 0

    # Phase events fired once per distinct phase.
    phases = sorted(e.get("phase") for e in _events(store, res.run_id, "phase_started"))
    assert phases == ["Phase 1: read", "Phase 2: verify"]

    # Done-criteria persisted for each step.
    rows = store.get_plan_steps(_latest_plan_id(store))
    assert len(rows) == 2
    for r in rows:
        assert json.loads(r["done_criteria"]) == {"diff_nonempty": True}
