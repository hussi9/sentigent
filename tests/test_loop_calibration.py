"""G1 proof: the cross-session loop is no longer calibration-blind.

When the loop blocks on a real blocker and pages the human, it persists the clone's
attempt as an escalation; when the human answers via loop_driver.answer(), the store
records a calibration event (was the clone directionally right?). These tests prove the
wiring end-to-end against a real MemoryStore on a temp DB — the mechanism that makes the
loop's push-vs-ask judgment actually learn from outcomes."""
import json

from sentigent.memory.store import MemoryStore
from sentigent.operator import loop_driver as L


def _store(tmp_path):
    return MemoryStore(agent_id="t", org_id="t", db_path=str(tmp_path / "brain.db"))


def test_blocker_category_buckets():
    assert L._blocker_category("deploy to prod") == "deploy"
    assert L._blocker_category("run pytest") == "tests"
    assert L._blocker_category("write the parser") == "general"


def test_persist_escalation_records_clone_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path)
    store = _store(tmp_path)
    monkeypatch.setattr(L, "_open_store", lambda: store)
    state = L.start("g", ["deploy the service"], cwd=str(tmp_path))
    step = state["steps"][0]
    attempt = {"decision": "approve", "confidence": 0.9, "category": "deploy"}
    eid = L._persist_escalation(state, step, attempt)
    assert eid
    escs = store.get_escalations(limit=10)
    row = next(e for e in escs if int(e["id"]) == eid)
    ctx = json.loads(row["context"]) if isinstance(row["context"], str) else row["context"]
    assert ctx["clone_attempt"]["decision"] == "approve"
    assert ctx["category"] == "deploy"


def test_answer_records_calibration(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path)
    store = _store(tmp_path)
    monkeypatch.setattr(L, "_open_store", lambda: store)
    # a loop blocked on a step, with the clone's attempt persisted
    state = L.start("g", ["deploy the service"], cwd=str(tmp_path))
    step = state["steps"][0]
    step["status"] = "failed"
    state["status"] = "blocked"
    eid = L._persist_escalation(state, step, {"decision": "approve", "confidence": 0.8,
                                              "category": "deploy"})
    state["open_escalation_id"] = eid
    state["open_escalation_step"] = step["i"]
    L._save(state)

    # human answers "approve" → clone was right → a calibration event is recorded
    out = L.answer(state["loop_id"], "approve")
    assert out["learned"].get("calibrated") is True
    assert out["status"] == "running"                      # step reopened, loop continues
    reload = L.load(state["loop_id"])
    assert reload["steps"][0]["status"] == "pending"
    assert "open_escalation_id" not in reload
    cal = store.get_calibration("deploy")
    assert cal                                             # calibration now has data for this category
