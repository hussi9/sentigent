"""Tests for operator run-safety primitives — KillSwitch (F2) + BudgetGovernor (F1)."""
from __future__ import annotations

import pytest

from sentigent.operator.safety import BudgetGovernor, BudgetStatus, KillSwitch


# --------------------------------------------------------------------------- #
# KillSwitch
# --------------------------------------------------------------------------- #
@pytest.fixture
def ks(tmp_path):
    return KillSwitch(flag_dir=str(tmp_path / "killswitch"))


def test_starts_untripped(ks):
    assert ks.is_tripped() is False
    assert ks.is_tripped("run-a") is False


def test_global_trip_clear(ks):
    ks.trip()
    assert ks.is_tripped() is True
    ks.clear()
    assert ks.is_tripped() is False


def test_global_trip_writes_flag_file(tmp_path):
    flag_dir = tmp_path / "killswitch"
    ks = KillSwitch(flag_dir=str(flag_dir))
    ks.trip()
    assert (flag_dir / "global.flag").exists()
    ks.clear()
    assert not (flag_dir / "global.flag").exists()


def test_clear_missing_flag_is_noop(ks):
    # Clearing something never tripped must not raise.
    ks.clear()
    ks.clear("never-existed")
    assert ks.is_tripped() is False


def test_per_run_isolation(ks):
    ks.trip("A")
    assert ks.is_tripped("A") is True
    # Tripping run A must NOT trip run B.
    assert ks.is_tripped("B") is False
    # And the global view (no run id) is also unaffected.
    assert ks.is_tripped() is False


def test_global_trips_every_run(ks):
    ks.trip()  # global
    assert ks.is_tripped("A") is True
    assert ks.is_tripped("B") is True
    assert ks.is_tripped() is True


def test_per_run_clear_does_not_touch_others(ks):
    ks.trip("A")
    ks.trip("B")
    ks.clear("A")
    assert ks.is_tripped("A") is False
    assert ks.is_tripped("B") is True


def test_per_run_flag_path(tmp_path):
    flag_dir = tmp_path / "killswitch"
    ks = KillSwitch(flag_dir=str(flag_dir))
    ks.trip("xyz")
    assert (flag_dir / "run-xyz.flag").exists()
    assert not (flag_dir / "global.flag").exists()


def test_reset_all_clears_everything(ks):
    ks.trip()
    ks.trip("A")
    ks.trip("B")
    ks.reset_all()
    assert ks.is_tripped() is False
    assert ks.is_tripped("A") is False
    assert ks.is_tripped("B") is False


def test_is_tripped_failsoft_on_fs_error(ks, monkeypatch):
    # If the FS check blows up, is_tripped returns False (never deadlock).
    def boom(self):
        raise OSError("filesystem gone")

    monkeypatch.setattr("pathlib.Path.exists", boom)
    assert ks.is_tripped() is False
    assert ks.is_tripped("A") is False


def test_default_flag_dir_expands_home():
    ks = KillSwitch()
    assert "~" not in str(ks.flag_dir)
    assert str(ks.flag_dir).endswith(".sentigent/killswitch")


# --------------------------------------------------------------------------- #
# BudgetGovernor
# --------------------------------------------------------------------------- #
def test_starts_at_zero():
    gov = BudgetGovernor(limit_usd=1.0)
    s = gov.status()
    assert isinstance(s, BudgetStatus)
    assert s.spent_usd == 0.0
    assert s.spent_tokens == 0
    assert s.exceeded is False
    assert s.remaining_usd == 1.0


def test_accrual_cost_math():
    gov = BudgetGovernor(limit_usd=10.0)
    # 1000 in @ 0.003 + 1000 out @ 0.015 = 0.018
    s = gov.add(1000, 1000)
    assert s.spent_usd == pytest.approx(0.018)
    assert s.spent_tokens == 2000
    assert s.exceeded is False
    assert s.remaining_usd == pytest.approx(10.0 - 0.018)


def test_accrual_accumulates():
    gov = BudgetGovernor(limit_usd=10.0)
    gov.add(1000, 0)  # 0.003
    s = gov.add(0, 1000)  # +0.015
    assert s.spent_usd == pytest.approx(0.018)
    assert s.spent_tokens == 2000


def test_custom_prices():
    gov = BudgetGovernor(
        limit_usd=10.0,
        price_per_1k_input_usd=0.001,
        price_per_1k_output_usd=0.002,
    )
    s = gov.add(2000, 1000)  # 2*0.001 + 1*0.002 = 0.004
    assert s.spent_usd == pytest.approx(0.004)


def test_exceeded_crossing_limit():
    gov = BudgetGovernor(limit_usd=0.02)
    s = gov.add(1000, 0)  # 0.003, under
    assert s.exceeded is False
    assert gov.exceeded() is False
    # Push over the 0.02 ceiling.
    s = gov.add(0, 2000)  # +0.030 => 0.033 total >= 0.02
    assert s.exceeded is True
    assert gov.exceeded() is True
    assert s.remaining_usd == 0.0


def test_exceeded_exact_limit_is_exceeded():
    gov = BudgetGovernor(
        limit_usd=0.003, price_per_1k_input_usd=0.003, price_per_1k_output_usd=0.0
    )
    s = gov.add(1000, 0)  # exactly 0.003, >= limit
    assert s.spent_usd == pytest.approx(0.003)
    assert s.exceeded is True


def test_unlimited_never_exceeds():
    for limit in (0, 0.0, -1):
        gov = BudgetGovernor(limit_usd=limit)
        gov.add(1_000_000, 1_000_000)  # huge spend
        assert gov.exceeded() is False
        s = gov.status()
        assert s.exceeded is False
        assert s.remaining_usd == 0.0  # unlimited reports 0 remaining headroom


def test_remaining_usd_math():
    gov = BudgetGovernor(limit_usd=1.0)
    gov.add(100_000, 0)  # 100 * 0.003 = 0.30
    assert gov.status().remaining_usd == pytest.approx(0.70)


def test_reset_clears_spend():
    gov = BudgetGovernor(limit_usd=0.01)
    gov.add(10_000, 10_000)
    assert gov.exceeded() is True
    gov.reset()
    s = gov.status()
    assert s.spent_usd == 0.0
    assert s.spent_tokens == 0
    assert s.exceeded is False
    assert s.remaining_usd == 0.01
