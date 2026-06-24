"""Tests for the tiny operator cost tracker (sentigent/operator/cost.py).

Uses tmp_path as cost_dir throughout — never touches the real ~/.sentigent home.
"""

from __future__ import annotations

import json

from sentigent.operator import cost


# ── cost_of (pure math) ───────────────────────────────────────────────


def test_cost_of_known_model() -> None:
    price = cost.PRICING["claude-sonnet-4-6"]
    # 1M input + 1M output → exactly in + out price
    assert cost.cost_of(1_000_000, 1_000_000, "claude-sonnet-4-6") == round(
        price["in"] + price["out"], 6
    )


def test_cost_of_scales_linearly() -> None:
    price = cost.PRICING["claude-opus-4-8"]
    # 500k input tokens → half the per-1M input price
    expected = round(price["in"] * 0.5, 6)
    assert cost.cost_of(500_000, 0, "claude-opus-4-8") == expected


def test_cost_of_unknown_model_falls_back_to_default() -> None:
    default = cost.PRICING["default"]
    expected = round(default["in"] + default["out"], 6)
    assert cost.cost_of(1_000_000, 1_000_000, "totally-made-up-model") == expected


def test_cost_of_is_rounded_to_six_dp() -> None:
    # A tiny token count must not produce a 17-digit float.
    val = cost.cost_of(1, 1, "claude-haiku-4-5")
    assert val == round(val, 6)


def test_cost_of_zero_tokens_is_zero() -> None:
    assert cost.cost_of(0, 0, "claude-opus-4-8") == 0.0


# ── record + summary roundtrip ─────────────────────────────────────────


def test_record_returns_event_and_writes_jsonl(tmp_path) -> None:
    event = cost.record(
        "loop-A",
        in_tokens=1_000_000,
        out_tokens=500_000,
        model="claude-sonnet-4-6",
        cost_dir=tmp_path,
    )
    assert event["loop_id"] == "loop-A"
    assert event["model"] == "claude-sonnet-4-6"
    assert event["in_tokens"] == 1_000_000
    assert event["out_tokens"] == 500_000
    assert event["usd"] == cost.cost_of(1_000_000, 500_000, "claude-sonnet-4-6")
    assert event.get("logged") is True

    log_file = tmp_path / "loop-A.jsonl"
    assert log_file.exists()
    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["usd"] == event["usd"]


def test_summary_roundtrip_single_loop(tmp_path) -> None:
    cost.record("loop-B", in_tokens=1_000_000, out_tokens=0,
                model="claude-opus-4-8", cost_dir=tmp_path)
    cost.record("loop-B", in_tokens=2_000_000, out_tokens=1_000_000,
                model="claude-haiku-4-5", cost_dir=tmp_path)

    s = cost.summary("loop-B", cost_dir=tmp_path)
    assert s["events"] == 2
    assert s["in_tokens"] == 3_000_000
    assert s["out_tokens"] == 1_000_000
    assert set(s["by_model"]) == {"claude-opus-4-8", "claude-haiku-4-5"}

    expected_total = round(
        cost.cost_of(1_000_000, 0, "claude-opus-4-8")
        + cost.cost_of(2_000_000, 1_000_000, "claude-haiku-4-5"),
        6,
    )
    assert s["total_usd"] == expected_total
    # by_model totals add up to total_usd
    assert round(sum(s["by_model"].values()), 6) == expected_total


def test_summary_all_loops_when_loop_id_none(tmp_path) -> None:
    cost.record("loop-X", in_tokens=1_000_000, out_tokens=0,
                model="claude-opus-4-8", cost_dir=tmp_path)
    cost.record("loop-Y", in_tokens=1_000_000, out_tokens=0,
                model="claude-opus-4-8", cost_dir=tmp_path)

    s = cost.summary(None, cost_dir=tmp_path)
    assert s["events"] == 2
    assert s["in_tokens"] == 2_000_000
    expected = round(2 * cost.cost_of(1_000_000, 0, "claude-opus-4-8"), 6)
    assert s["total_usd"] == expected


def test_summary_empty_dir_is_zeros(tmp_path) -> None:
    s = cost.summary("nope", cost_dir=tmp_path)
    assert s == {
        "total_usd": 0.0,
        "in_tokens": 0,
        "out_tokens": 0,
        "by_model": {},
        "events": 0,
    }


def test_summary_all_loops_empty_dir_is_zeros(tmp_path) -> None:
    s = cost.summary(None, cost_dir=tmp_path)
    assert s["total_usd"] == 0.0
    assert s["events"] == 0
    assert s["by_model"] == {}


def test_summary_usd_rounded(tmp_path) -> None:
    cost.record("loop-r", in_tokens=1, out_tokens=1,
                model="claude-opus-4-8", cost_dir=tmp_path)
    s = cost.summary("loop-r", cost_dir=tmp_path)
    assert s["total_usd"] == round(s["total_usd"], 6)


# ── fail-soft ──────────────────────────────────────────────────────────


def test_record_failsoft_on_unwritable_dir(tmp_path) -> None:
    # Point cost_dir at a *file* so the dir cannot be created → write fails.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    event = cost.record("loop-Z", in_tokens=10, out_tokens=10,
                        model="default", cost_dir=blocker)
    # Never raises; reports it could not log but still returns the event.
    assert event["logged"] is False
    assert event["loop_id"] == "loop-Z"
    assert event["usd"] == cost.cost_of(10, 10, "default")
