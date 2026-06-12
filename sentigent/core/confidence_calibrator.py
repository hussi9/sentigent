"""confidence_calibrator.py — G3 ConfidenceCalibrator.

Graduates autonomy automatically, per-domain. Reads the honest calibration
ledger ("when the operator was confident, was it actually right?") and maps each
domain's success-rate + sample-size onto a recommended autonomy level.

This is what makes the autonomy ladder self-driving: high calibration in
'frontend' but low in 'db' => autopilot the former, copilot the latter. Thin
data never earns trust — a domain with too few samples stays in 'copilot' where
every step is one-tap approved and the profile keeps harvesting signal.

Local-first, fail-soft, deterministic. Never raises. See
docs/plans/2026-06-03-operator-autopilot-design.md (G3, H1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Autonomy ladder (H1), weakest -> strongest trust.
COPILOT = "copilot"
ASSISTED = "assisted"
AUTOPILOT = "autopilot"
TRUSTED = "trusted"

# Minimum samples before we trust a rate at all. Below this the data is too thin
# to distinguish a good domain from a lucky one => stay in copilot (harvest more).
MIN_SAMPLES = 5


@dataclass
class DomainCalibration:
    domain: str
    total: int
    correct: int
    rate: float
    recommended_autonomy: str  # copilot | assisted | autopilot | trusted
    rationale: str

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "total": self.total,
            "correct": self.correct,
            "rate": round(self.rate, 4),
            "recommended_autonomy": self.recommended_autonomy,
            "rationale": self.rationale,
        }


def _recommend(total: int, correct: int, rate: float) -> tuple[str, str]:
    """Map (sample-size, success-rate) -> (autonomy, plain-words rationale).

    Thresholds (a minimum sample size guards against over-trusting thin data):
      <5 samples              => copilot   (need more signal)
      rate>=0.9 & n>=20       => trusted
      rate>=0.8 & n>=10       => autopilot
      rate>=0.6               => assisted
      else                    => copilot
    """
    pct = int(round(rate * 100))
    if total < MIN_SAMPLES:
        return (
            COPILOT,
            f"Only {total} sample(s) so far — too thin to trust. Staying in copilot "
            f"to keep harvesting signal before graduating autonomy.",
        )
    if rate >= 0.9 and total >= 20:
        return (
            TRUSTED,
            f"{pct}% correct across {total} decisions — strongly calibrated. "
            f"Trusted: escalate rarely (PolicyWall still inviolable).",
        )
    if rate >= 0.8 and total >= 10:
        return (
            AUTOPILOT,
            f"{pct}% correct across {total} decisions — reliable. Autopilot: run "
            f"unattended, escalate only on real triggers.",
        )
    if rate >= 0.6:
        return (
            ASSISTED,
            f"{pct}% correct across {total} decisions — decent but not proven. "
            f"Assisted: auto-proceed low-risk, ask on risky/novel.",
        )
    return (
        COPILOT,
        f"Only {pct}% correct across {total} decisions — unreliable here. Copilot: "
        f"propose each step for one-tap approval until the rate climbs.",
    )


def _default(domain: str) -> DomainCalibration:
    auto, why = _recommend(0, 0, 0.0)
    return DomainCalibration(
        domain=domain,
        total=0,
        correct=0,
        rate=0.0,
        recommended_autonomy=auto,
        rationale=why,
    )


class ConfidenceCalibrator:
    """Reads store.get_calibration() and recommends an autonomy level per domain."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def calibrate(self) -> list[DomainCalibration]:
        """All seen domains -> their recommended autonomy, sorted by domain name.
        Fail-soft: returns [] if the calibration ledger is unreadable."""
        try:
            data = self.store.get_calibration() or {}
        except Exception:
            return []
        out: list[DomainCalibration] = []
        for domain in sorted(data.keys()):
            stats = data[domain] or {}
            total = int(stats.get("total", 0) or 0)
            correct = int(stats.get("correct", 0) or 0)
            rate = float(stats.get("rate", 0.0) or 0.0)
            auto, why = _recommend(total, correct, rate)
            out.append(
                DomainCalibration(
                    domain=domain,
                    total=total,
                    correct=correct,
                    rate=rate,
                    recommended_autonomy=auto,
                    rationale=why,
                )
            )
        return out

    def for_domain(self, domain: str) -> DomainCalibration:
        """Calibration for one domain. Returns a safe copilot default if unseen."""
        try:
            data = self.store.get_calibration(domain=domain) or {}
        except Exception:
            data = {}
        stats = data.get(domain)
        if not stats:
            return _default(domain)
        total = int(stats.get("total", 0) or 0)
        correct = int(stats.get("correct", 0) or 0)
        rate = float(stats.get("rate", 0.0) or 0.0)
        auto, why = _recommend(total, correct, rate)
        return DomainCalibration(
            domain=domain,
            total=total,
            correct=correct,
            rate=rate,
            recommended_autonomy=auto,
            rationale=why,
        )

    def to_dict(self) -> dict:
        """{domain: DomainCalibration.to_dict()} for the whole ledger."""
        return {dc.domain: dc.to_dict() for dc in self.calibrate()}

    def recommendations(self) -> dict:
        """{domain: recommended_autonomy} — the compact form the learner folds in."""
        return {dc.domain: dc.recommended_autonomy for dc in self.calibrate()}
