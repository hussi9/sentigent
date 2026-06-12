"""Run-safety primitives for the Sentigent Operator (Fly mode) — F1/F2.

Two inviolable run controls the unattended runner leans on between steps:

- KillSwitch (F2): an instant stop via a file flag, global or per-run. It uses
  the filesystem on purpose so it survives across processes — a human (or another
  process) can drop a flag file and the running operator notices on its next poll.
  Fail-soft: is_tripped() never raises; on an FS error it returns False so a
  flaky filesystem can't deadlock the runner. trip() tries hard (it's the safety
  brake — a failure there is worth knowing about, but we still never raise).

- BudgetGovernor (F1): a hard token/$ ceiling per run. Pure local accounting —
  accrue cost as the run spends tokens, and the runner refuses the next step once
  the ceiling is crossed. Default prices are Claude-class but overridable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# --------------------------------------------------------------------------- #
# F2 — KillSwitch
# --------------------------------------------------------------------------- #
class KillSwitch:
    """Instant stop via a file flag — global or per-run. Survives across
    processes (the unattended runner polls is_tripped() between steps)."""

    GLOBAL_FLAG = "global.flag"

    def __init__(self, flag_dir: str | None = None) -> None:
        if flag_dir is None:
            flag_dir = os.path.join("~", ".sentigent", "killswitch")
        self.flag_dir = Path(flag_dir).expanduser()
        try:
            self.flag_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Fail-soft: if we can't make the dir now, trip()/is_tripped() will
            # try again / degrade gracefully rather than crashing the runner.
            pass

    def _flag_path(self, run_id: str | None) -> Path:
        if run_id is None:
            return self.flag_dir / self.GLOBAL_FLAG
        return self.flag_dir / f"run-{run_id}.flag"

    def trip(self, run_id: str | None = None) -> None:
        """Set the kill flag. run_id=None => global stop (trips every run).

        This is the safety brake, so we try hard: ensure the dir exists and
        write the file. We still never raise (a runner shouldn't crash because
        the brake itself hiccuped), but trip is the one op that should succeed.
        """
        path = self._flag_path(run_id)
        try:
            self.flag_dir.mkdir(parents=True, exist_ok=True)
            path.write_text("tripped", encoding="utf-8")
        except OSError:
            pass

    def clear(self, run_id: str | None = None) -> None:
        """Remove the kill flag. Ignore if it was never set."""
        path = self._flag_path(run_id)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def is_tripped(self, run_id: str | None = None) -> bool:
        """True if the GLOBAL flag is set OR this run_id's flag is set.

        Fail-soft: any FS error returns False so a broken filesystem can't
        wedge the runner into a permanent stop it can never observe/clear.
        """
        try:
            if (self.flag_dir / self.GLOBAL_FLAG).exists():
                return True
            if run_id is not None and self._flag_path(run_id).exists():
                return True
            return False
        except OSError:
            return False

    def reset_all(self) -> None:
        """Clear every flag in the dir (global + all per-run). Test helper."""
        try:
            for entry in self.flag_dir.glob("*.flag"):
                try:
                    entry.unlink()
                except OSError:
                    pass
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# F1 — BudgetGovernor
# --------------------------------------------------------------------------- #
@dataclass
class BudgetStatus:
    spent_usd: float
    limit_usd: float
    spent_tokens: int
    exceeded: bool
    remaining_usd: float


class BudgetGovernor:
    """Hard token/$ ceiling per run. Default prices are for a Claude-class
    model; overridable. Local accounting only."""

    def __init__(
        self,
        limit_usd: float,
        price_per_1k_input_usd: float = 0.003,
        price_per_1k_output_usd: float = 0.015,
    ) -> None:
        self.limit_usd = limit_usd
        self.price_per_1k_input_usd = price_per_1k_input_usd
        self.price_per_1k_output_usd = price_per_1k_output_usd
        self._spent_usd: float = 0.0
        self._spent_tokens: int = 0

    def add(self, input_tokens: int, output_tokens: int) -> BudgetStatus:
        """Accrue the cost of one step's token usage; return current status."""
        cost = (
            (input_tokens / 1000.0) * self.price_per_1k_input_usd
            + (output_tokens / 1000.0) * self.price_per_1k_output_usd
        )
        self._spent_usd += cost
        self._spent_tokens += int(input_tokens) + int(output_tokens)
        return self.status()

    def exceeded(self) -> bool:
        """True once spend reaches the ceiling. limit_usd<=0 => unlimited."""
        if self.limit_usd <= 0:
            return False
        return self._spent_usd >= self.limit_usd

    def status(self) -> BudgetStatus:
        if self.limit_usd <= 0:
            remaining = 0.0
        else:
            remaining = max(0.0, self.limit_usd - self._spent_usd)
        return BudgetStatus(
            spent_usd=self._spent_usd,
            limit_usd=self.limit_usd,
            spent_tokens=self._spent_tokens,
            exceeded=self.exceeded(),
            remaining_usd=remaining,
        )

    def reset(self) -> None:
        self._spent_usd = 0.0
        self._spent_tokens = 0
