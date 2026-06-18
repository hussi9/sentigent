"""Tests for sentigent/operator/scheduler.py — the unattended cadence.

Fully deterministic: a temp LOOP_DIR (monkeypatched onto loop_driver.LOOP_DIR, the
same way the driver's own tests do), a fake `_driver` so nothing real is driven, and
a stub `_sleep` that records calls but never actually sleeps. No clock, no `claude`,
no network, no real subprocess.
"""
import json

from sentigent.operator import loop_driver as L
from sentigent.operator import scheduler as S


# ── fixtures / helpers ────────────────────────────────────────────────────────────
def _write_loop(loop_dir, loop_id, *, status="running", step_statuses, created_at=0.0):
    """Drop a minimal loop JSON on disk in the shape pending_loops reads."""
    state = {
        "loop_id": loop_id,
        "goal": f"goal for {loop_id}",
        "status": status,
        "created_at": created_at,
        "steps": [
            {"i": i, "text": f"step {i}", "status": s}
            for i, s in enumerate(step_statuses)
        ],
    }
    (loop_dir / f"{loop_id}.json").write_text(json.dumps(state))
    return state


def _mixed_dir(tmp_path):
    """A LOOP_DIR with one loop in each meaningful state."""
    _write_loop(tmp_path, "loop_aaaaaa", status="running",
                step_statuses=["done", "pending"], created_at=1.0)   # pickable
    _write_loop(tmp_path, "loop_bbbbbb", status="running",
                step_statuses=["done", "done"], created_at=2.0)      # no work left
    _write_loop(tmp_path, "loop_cccccc", status="done",
                step_statuses=["done"], created_at=3.0)              # terminal
    _write_loop(tmp_path, "loop_dddddd", status="blocked",
                step_statuses=["failed"], created_at=4.0)            # human-gated
    _write_loop(tmp_path, "loop_eeeeee", status="running",
                step_statuses=["pending", "pending"], created_at=0.5)  # pickable (oldest)
    return tmp_path


# ── pending_loops ──────────────────────────────────────────────────────────────────
def test_pending_loops_missing_dir_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path / "nope")
    assert S.pending_loops() == []


def test_pending_loops_filters_to_only_loops_with_work(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", _mixed_dir(tmp_path))
    pend = S.pending_loops()
    # only the two running loops that still have a pending step
    assert set(pend) == {"loop_aaaaaa", "loop_eeeeee"}
    # excluded: completed-but-running (bbbbbb), terminal done (cccccc), blocked (dddddd)
    assert "loop_bbbbbb" not in pend
    assert "loop_cccccc" not in pend
    assert "loop_dddddd" not in pend


def test_pending_loops_sorted_oldest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", _mixed_dir(tmp_path))
    # eeeeee created_at 0.5 < aaaaaa created_at 1.0 → FIFO
    assert S.pending_loops() == ["loop_eeeeee", "loop_aaaaaa"]


def test_pending_loops_explicit_dir_arg_overrides_loop_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path / "ignored")
    real = tmp_path / "real"
    real.mkdir()
    _write_loop(real, "loop_ffffff", step_statuses=["pending"])
    assert S.pending_loops(loop_dir=real) == ["loop_ffffff"]


def test_pending_loops_skips_garbled_json(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path)
    (tmp_path / "loop_garbage.json").write_text("{not json")
    _write_loop(tmp_path, "loop_aaaaaa", step_statuses=["pending"])
    assert S.pending_loops() == ["loop_aaaaaa"]  # bad file ignored, good one kept


# ── tick ────────────────────────────────────────────────────────────────────────
def test_tick_drives_only_pending_loops(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", _mixed_dir(tmp_path))
    seen = []

    def fake_driver(loop_id, execute=False):
        seen.append((loop_id, execute))
        return {"status": "ok", "loop_id": loop_id}

    res = S.tick(execute=True, _driver=fake_driver)
    assert set(res["driven"]) == {"loop_eeeeee", "loop_aaaaaa"}
    assert set(d[0] for d in seen) == {"loop_eeeeee", "loop_aaaaaa"}
    assert all(d[1] is True for d in seen)  # execute flag forwarded
    assert res["results"]["loop_aaaaaa"]["status"] == "ok"


def test_tick_is_failsoft_per_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", _mixed_dir(tmp_path))

    def boom_driver(loop_id, execute=False):
        if loop_id == "loop_eeeeee":
            raise RuntimeError("kaboom")
        return {"status": "ok", "loop_id": loop_id}

    res = S.tick(_driver=boom_driver)
    # the raising loop is recorded as an error; the other still drove fine
    assert res["results"]["loop_eeeeee"] == {"error": "kaboom"}
    assert res["results"]["loop_aaaaaa"]["status"] == "ok"
    assert set(res["driven"]) == {"loop_eeeeee", "loop_aaaaaa"}


def test_tick_remaining_reflects_post_pass_state(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path)
    _write_loop(tmp_path, "loop_aaaaaa", step_statuses=["pending"], created_at=1.0)

    # driver that marks the loop done on disk so post-pass pending count drops
    def completing_driver(loop_id, execute=False):
        p = tmp_path / f"{loop_id}.json"
        st = json.loads(p.read_text())
        for s in st["steps"]:
            s["status"] = "done"
        st["status"] = "done"
        p.write_text(json.dumps(st))
        return st

    res = S.tick(_driver=completing_driver)
    assert res["driven"] == ["loop_aaaaaa"]
    assert res["remaining"] == 0


def test_tick_empty_dir_drives_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path)
    res = S.tick(_driver=lambda *a, **k: {})
    assert res == {"driven": [], "results": {}, "remaining": 0}


# ── run_forever ───────────────────────────────────────────────────────────────────
def test_run_forever_yields_exactly_max_ticks():
    ticks = []
    sleeps = []

    def stub_tick(**kw):
        ticks.append(kw)
        return {"driven": [], "results": {}, "remaining": 0}

    results = list(
        S.run_forever(99.0, _sleep=lambda s: sleeps.append(s), _tick=stub_tick, max_ticks=3)
    )
    assert len(results) == 3
    assert len(ticks) == 3
    # sleeps only BETWEEN ticks: 3 ticks → 2 sleeps, none after the last
    assert sleeps == [99.0, 99.0]


def test_run_forever_never_really_sleeps_and_passes_interval():
    sleeps = []
    list(
        S.run_forever(
            42.0,
            _sleep=lambda s: sleeps.append(s),
            _tick=lambda **kw: {"driven": [], "results": {}, "remaining": 0},
            max_ticks=2,
        )
    )
    assert sleeps == [42.0]  # exactly one sleep between two ticks


def test_run_forever_zero_ticks_yields_nothing():
    sleeps = []
    results = list(
        S.run_forever(1.0, _sleep=lambda s: sleeps.append(s),
                      _tick=lambda **kw: {}, max_ticks=0)
    )
    assert results == []
    assert sleeps == []


def test_run_forever_forwards_execute_and_loop_dir():
    seen = []

    def stub_tick(**kw):
        seen.append(kw)
        return {}

    list(S.run_forever(1.0, _sleep=lambda s: None, _tick=stub_tick,
                       max_ticks=1, execute=True, loop_dir="/tmp/whatever"))
    assert seen == [{"execute": True, "loop_dir": "/tmp/whatever"}]


# ── seed_from_backlog ─────────────────────────────────────────────────────────────
def test_seed_from_backlog_missing_file_returns_empty(tmp_path):
    assert S.seed_from_backlog(tmp_path / "nope.toml") == []


def test_seed_from_backlog_starts_a_loop_per_task(tmp_path):
    backlog = tmp_path / "backlog.toml"
    backlog.write_text(
        '[[task]]\n'
        'goal = "ship the parser"\n'
        'steps = ["scaffold", "tokenizer"]\n'
        'verify = "pytest -q"\n'
        '\n'
        '[[task]]\n'
        'goal = "write docs"\n'
        'steps = ["outline"]\n'
    )
    calls = []

    def fake_start(goal, steps, cwd=".", **kwargs):
        calls.append((goal, steps, cwd, kwargs))
        return {"loop_id": f"loop_{len(calls):06d}"}

    ids = S.seed_from_backlog(backlog, _start=fake_start)
    assert ids == ["loop_000001", "loop_000002"]
    assert calls[0][0] == "ship the parser"
    assert calls[0][1] == ["scaffold", "tokenizer"]
    assert calls[0][3] == {"verify_cmd": "pytest -q"}
    assert calls[1][0] == "write docs"
    assert calls[1][3] == {}  # no verify → no verify_cmd kwarg


def test_seed_from_backlog_skips_invalid_tasks(tmp_path):
    backlog = tmp_path / "backlog.toml"
    backlog.write_text(
        '[[task]]\n'
        'goal = "no steps here"\n'      # missing steps → skipped
        '\n'
        '[[task]]\n'
        'steps = ["orphan"]\n'          # missing goal → skipped
        '\n'
        '[[task]]\n'
        'goal = "good one"\n'
        'steps = ["do it"]\n'
    )
    started = []
    ids = S.seed_from_backlog(
        backlog, _start=lambda g, s, c=".", **k: (started.append(g) or {"loop_id": "loop_999999"})
    )
    assert started == ["good one"]
    assert ids == ["loop_999999"]


def test_seed_from_backlog_garbled_toml_returns_empty(tmp_path):
    backlog = tmp_path / "backlog.toml"
    backlog.write_text("this is = = not valid toml [[[")
    assert S.seed_from_backlog(backlog, _start=lambda *a, **k: {"loop_id": "x"}) == []
