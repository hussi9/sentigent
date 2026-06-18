"""Tests for sentigent/operator/parallel.py — the parallel fan-out (roadmap X1).

Deterministic: a fake `_driver` returns canned summaries (one raises) so no real
agents/subprocesses ever spawn. Covers fail-soft, combined_fap math, all ids
present, and that the work actually ran concurrently.
"""
import threading
import time

from sentigent.operator import parallel as P


# ── combined_fap (pure) ─────────────────────────────────────────────────────────
def test_combined_fap_empty_is_zero():
    assert P.combined_fap([]) == 0.0


def test_combined_fap_mean_of_fap():
    summaries = [{"FAP": 1.0}, {"FAP": 0.0}, {"FAP": 0.5}]
    assert P.combined_fap(summaries) == 0.5


def test_combined_fap_treats_missing_or_errored_as_zero():
    # a summary with no FAP, and an error record, both count as 0
    summaries = [{"FAP": 1.0}, {"error": "boom"}, {"steps": []}]
    assert P.combined_fap(summaries) == round(1.0 / 3, 6)


def test_combined_fap_reads_fap_from_loop_state_metrics():
    # a real loop_driver state has no top-level FAP; combined_fap derives it
    state = {"steps": [
        {"status": "done", "verified": True},
        {"status": "done", "verified": True},
    ], "asks": 0, "clone_resolves": 0}
    assert P.combined_fap([state]) == 1.0


# ── drive_many ───────────────────────────────────────────────────────────────────
def _done_state(n):
    return {"steps": [{"status": "done", "verified": True} for _ in range(n)],
            "asks": 0, "clone_resolves": 0, "status": "done"}


def test_drive_many_all_ids_present_and_fap_math():
    summaries = {
        "loop_aaaaaa": {"FAP": 1.0, "steps": [{"status": "done", "verified": True}]},
        "loop_bbbbbb": {"FAP": 0.0, "steps": [{"status": "failed", "verified": False}]},
    }

    def fake_driver(loop_id, execute=False, **kw):
        return summaries[loop_id]

    out = P.drive_many(["loop_aaaaaa", "loop_bbbbbb"], _driver=fake_driver)
    assert set(out["results"]) == {"loop_aaaaaa", "loop_bbbbbb"}
    assert out["loops"] == 2
    assert out["combined_fap"] == 0.5
    assert out["results"]["loop_aaaaaa"]["FAP"] == 1.0


def test_drive_many_fail_soft_one_loop_raises():
    def fake_driver(loop_id, execute=False, **kw):
        if loop_id == "loop_bad000":
            raise RuntimeError("agent exploded")
        return {"FAP": 1.0, "steps": [{"status": "done", "verified": True}]}

    out = P.drive_many(["loop_good00", "loop_bad000"], _driver=fake_driver)
    # never raises; bad loop recorded as an error, good loop survives
    assert "error" in out["results"]["loop_bad000"]
    assert "agent exploded" in out["results"]["loop_bad000"]["error"]
    assert out["results"]["loop_good00"]["FAP"] == 1.0
    # errored loop counts as FAP 0 → mean of [1.0, 0.0]
    assert out["combined_fap"] == 0.5
    assert out["loops"] == 2


def test_drive_many_completed_counts_all_steps_done():
    def fake_driver(loop_id, execute=False, **kw):
        if loop_id == "loop_full00":
            return _done_state(2)
        # one step still pending → not completed
        return {"steps": [{"status": "done", "verified": True},
                          {"status": "pending", "verified": None}],
                "asks": 0, "clone_resolves": 0}

    out = P.drive_many(["loop_full00", "loop_part00"], _driver=fake_driver)
    assert out["completed"] == 1


def test_drive_many_empty_list():
    out = P.drive_many([], _driver=lambda *a, **k: {})
    assert out["loops"] == 0
    assert out["completed"] == 0
    assert out["combined_fap"] == 0.0
    assert out["results"] == {}


def test_drive_many_passes_execute_flag_through():
    seen = {}

    def fake_driver(loop_id, execute=False, **kw):
        seen[loop_id] = execute
        return {"FAP": 1.0}

    P.drive_many(["loop_zzzzzz"], execute=True, _driver=fake_driver)
    assert seen["loop_zzzzzz"] is True


def test_drive_many_runs_concurrently():
    # Each fake drive blocks on a barrier; if they run concurrently the barrier
    # releases. If serial, the barrier (with a short timeout) would time out.
    n = 4
    barrier = threading.Barrier(n, timeout=5)
    crossed = []

    def fake_driver(loop_id, execute=False, **kw):
        barrier.wait()  # only returns if all n threads reach here together
        crossed.append(loop_id)
        return {"FAP": 1.0}

    ids = [f"loop_{i:06d}" for i in range(n)]
    out = P.drive_many(ids, max_workers=n, _driver=fake_driver)
    assert len(crossed) == n
    assert out["loops"] == n
    assert out["combined_fap"] == 1.0


def test_drive_many_default_driver_is_loop_driver_drive():
    from sentigent.operator import loop_driver
    # smoke: with no _driver injected it wires to loop_driver.drive (we don't call
    # it — just assert the module exposes the wiring symbol).
    assert callable(loop_driver.drive)
    assert P._default_driver() is loop_driver.drive
