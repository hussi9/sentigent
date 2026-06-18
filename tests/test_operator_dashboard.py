"""Tests for the operator dashboard data layer (state())."""
from __future__ import annotations

import importlib

import pytest

from sentigent.operator import dashboard as D
from sentigent.operator import loop_driver as L


def test_state_empty_is_failsoft(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path / "loops")
    s = D.state(loop_dir=tmp_path / "loops", cost_dir=tmp_path / "cost", root=str(tmp_path))
    assert set(s) >= {"aggregate", "loops", "pending", "cost", "project_map"}
    assert s["loops"] == []
    assert s["aggregate"]["loops"] == 0
    assert s["aggregate"]["cost_usd"] == 0
    assert s["pending"] == []


def test_state_reports_a_loop(tmp_path, monkeypatch):
    loops = tmp_path / "loops"
    monkeypatch.setattr(L, "LOOP_DIR", loops)
    lid = L.start("ship export", ["write parser", "add tests"], verify_cmd="pytest -q")["loop_id"]

    s = D.state(loop_dir=loops, cost_dir=tmp_path / "cost", root=str(tmp_path))
    assert s["aggregate"]["loops"] >= 1
    ids = [x["loop_id"] for x in s["loops"]]
    assert lid in ids
    one = next(x for x in s["loops"] if x["loop_id"] == lid)
    assert one["goal"] == "ship export"
    assert "fap" in one
    # the DoD contract checklist is attached
    assert "criteria" in one and len(one["criteria"]) == 2
    # a fresh loop has nothing verified yet
    assert one["all_passed"] is False
    # and it shows up as pending work for the scheduler
    assert lid in s["pending"]


def test_state_includes_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path / "loops")
    cost_dir = tmp_path / "cost"
    try:
        from sentigent.operator import cost as C
        C.record("loop_x", in_tokens=1000, out_tokens=500, model="claude-haiku-4-5", cost_dir=cost_dir)
        s = D.state(loop_dir=tmp_path / "loops", cost_dir=cost_dir, root=str(tmp_path))
        assert s["cost"]["events"] >= 1
        assert s["aggregate"]["cost_usd"] > 0
    except ImportError:  # pragma: no cover
        pytest.skip("cost module not present")


def test_page_is_self_contained():
    # the HTML shell renders without a build step and has the live poller
    assert "/api/state" in D._PAGE
    assert "Figtree" in D._PAGE
