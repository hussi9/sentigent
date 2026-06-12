"""profile_learner.py — G2 ProfileLearner. Closes the learning loop.

The compounding piece. Every run's escalations + the user's answers + their
reverts feed back into (1) the per-domain calibration ledger, (2) plain-language
drift signals, and (3) — when the signal is strong — a new operator_profile
version with tightened 'ask_when' rules for the domains that keep going wrong.

The result: each run needs the user less. High calibration => the autonomy ladder
(ConfidenceCalibrator) graduates the domain; repeated reverts => the profile
learns to ask first.

Design constraints (locked):
  * Local-first, deterministic core (pure counting). The LLM is OPTIONAL and only
    used to phrase a proposed practice nicely — guarded by llm_available(),
    fail-soft, default OFF.
  * Never raises.
  * Idempotent-ish: we stamp '_last_learn_ts' into the profile_json and only
    process escalations / decision-events NEWER than it, so re-running doesn't
    double-count.

See docs/plans/2026-06-03-operator-autopilot-design.md (G2).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from sentigent.core.confidence_calibrator import ConfidenceCalibrator

# When a domain is reverted at least this many times in the window, that's drift.
REVERT_DRIFT_THRESHOLD = 2
# A domain with this many samples and a sub-coin-flip rate is also drift.
LOW_RATE_THRESHOLD = 0.5
LOW_RATE_MIN_SAMPLES = 5
# Below this calibration rate (with enough samples) we fold an 'ask_when' rule in.
ASK_WHEN_RATE = 0.6
ASK_WHEN_MIN_SAMPLES = 3

# A small library of guarding practices keyed by domain, used when a domain keeps
# getting reverted. Generic fallback covers any domain we don't have a phrase for.
_GUARD_PRACTICES = {
    "db": "Always run a migration in staging before prod, and back up first.",
    "database": "Always run a migration in staging before prod, and back up first.",
    "deploy": "Deploy to a preview/staging target and smoke-test before promoting to prod.",
    "frontend": "Verify the change in a real browser before considering it done.",
    "security": "Get a second review on anything touching auth, secrets, or permissions.",
    "infra": "Dry-run infra changes (plan/--dry-run) and confirm the diff before applying.",
}


@dataclass
class LearnResult:
    calibration_recorded: int = 0          # answered escalations + reverts turned into calibration
    drift_signals: list[str] = field(default_factory=list)
    proposed_practice: str = ""            # one concrete guarding practice, or ""
    autonomy_recommendations: dict = field(default_factory=dict)  # {domain: level}
    profile_version: int = -1             # new profile version written, else -1

    def to_dict(self) -> dict:
        return {
            "calibration_recorded": self.calibration_recorded,
            "drift_signals": list(self.drift_signals),
            "proposed_practice": self.proposed_practice,
            "autonomy_recommendations": dict(self.autonomy_recommendations),
            "profile_version": self.profile_version,
        }


def _domain_from_context(ctx: Any) -> str:
    """Pull a domain out of an escalation's context JSON. Fallback 'global'."""
    if isinstance(ctx, str):
        if not ctx.strip():
            return "global"
        try:
            ctx = json.loads(ctx)
        except Exception:
            return "global"
    if isinstance(ctx, dict):
        for key in ("domain", "category", "area"):
            val = ctx.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return "global"


def _is_plain_approve(decision: str) -> bool:
    """True when the user simply approved — i.e. the ask was probably unnecessary.
    Skip / takeover / redirect / deny all mean the ask was VALUABLE."""
    d = (decision or "").strip().lower()
    if not d:
        return False
    approve_words = ("approve", "approved", "yes", "ok", "okay", "go", "proceed", "continue")
    # Any sign of a non-approval verb means the ask earned its keep.
    veto_words = ("skip", "no", "deny", "reject", "stop", "takeover", "take over",
                  "redirect", "instead", "wait", "don't", "dont")
    if any(w in d for w in veto_words):
        return False
    return any(d == w or d.startswith(w + " ") or d == w + "." or w in d.split()
               for w in approve_words) or d in approve_words


class ProfileLearner:
    """Reads the real signal and folds it back into calibration + the profile."""

    def __init__(self, store: Any, model: Optional[str] = None) -> None:
        self.store = store
        self.model = model
        self.calibrator = ConfidenceCalibrator(store)

    # ---- profile_json read/write helpers (fail-soft) ----------------------

    def _load_profile_json(self) -> tuple[dict, float]:
        """Return (profile_dict, last_learn_ts). Empty dict / 0.0 if none."""
        try:
            row = self.store.get_latest_operator_profile()
        except Exception:
            row = None
        if not row:
            return {}, 0.0
        raw = row.get("profile_json") if isinstance(row, dict) else None
        try:
            prof = json.loads(raw) if raw else {}
        except Exception:
            prof = {}
        if not isinstance(prof, dict):
            prof = {}
        last = 0.0
        try:
            last = float(prof.get("_last_learn_ts", 0.0) or 0.0)
        except Exception:
            last = 0.0
        return prof, last

    # ---- the loop ----------------------------------------------------------

    def learn(self) -> LearnResult:
        """Close the loop. Fully fail-soft — never raises."""
        try:
            return self._learn()
        except Exception as exc:  # pragma: no cover - defensive
            return LearnResult(drift_signals=[f"learn() failed soft: {exc}"])

    def _learn(self) -> LearnResult:
        result = LearnResult()
        prof, last_learn_ts = self._load_profile_json()
        now = time.time()
        recorded = 0
        # Track per-domain revert counts seen this window for drift detection.
        revert_counts: dict[str, int] = {}

        # 1) Answered escalations newer than _last_learn_ts -> calibrate the
        #    ESCALATE prediction. A plain 'approve' on the ask suggests we
        #    over-asked (was_correct False); anything else means the ask was
        #    valuable (was_correct True).
        try:
            escalations = self.store.get_escalations(status="answered", limit=200) or []
        except Exception:
            escalations = []
        for esc in escalations:
            ts = self._ts(esc, "answered_at") or self._ts(esc, "ts")
            if ts <= last_learn_ts:
                continue
            domain = _domain_from_context(esc.get("context"))
            decision = esc.get("user_decision", "")
            was_correct = not _is_plain_approve(decision)
            try:
                self.store.record_calibration(
                    domain, predicted="escalate", was_correct=was_correct,
                    source="escalation_answer",
                )
                recorded += 1
            except Exception:
                pass

        # 2) Decision events newer than _last_learn_ts. A 'revert' means the
        #    clone's prior 'continue' was WRONG. An 'approve' means it was right.
        for kind, correct in (("revert", False), ("approve", True)):
            try:
                events = self.store.get_decision_events(limit=200, kind=kind) or []
            except Exception:
                events = []
            for ev in events:
                ts = self._ts(ev, "ts")
                if ts <= last_learn_ts:
                    continue
                domain = (ev.get("domain") or "global") or "global"
                try:
                    self.store.record_calibration(
                        domain, predicted="continue", was_correct=correct,
                        source=kind,
                    )
                    recorded += 1
                except Exception:
                    pass
                if kind == "revert":
                    revert_counts[domain] = revert_counts.get(domain, 0) + 1

        result.calibration_recorded = recorded

        # 3) Drift signals: domains with >=2 recent reverts, or a low rate w/ enough n.
        try:
            calib = self.store.get_calibration() or {}
        except Exception:
            calib = {}
        drift: list[str] = []
        worst_revert_domain = ""
        worst_revert_n = 0
        for domain, n in sorted(revert_counts.items(), key=lambda kv: -kv[1]):
            if n >= REVERT_DRIFT_THRESHOLD:
                drift.append(
                    f"you've reverted {n} '{domain}' step(s) — tightening {domain}"
                )
                if n > worst_revert_n:
                    worst_revert_n, worst_revert_domain = n, domain
        for domain, stats in sorted(calib.items()):
            total = int((stats or {}).get("total", 0) or 0)
            rate = float((stats or {}).get("rate", 0.0) or 0.0)
            if total >= LOW_RATE_MIN_SAMPLES and rate < LOW_RATE_THRESHOLD:
                msg = (f"'{domain}' is only {int(round(rate * 100))}% reliable over "
                       f"{total} decisions — keeping it on a short leash")
                if msg not in drift:
                    drift.append(msg)
        result.drift_signals = drift

        # 4) Proposed practice: if a domain keeps getting reverted, suggest a guard.
        if worst_revert_domain:
            result.proposed_practice = self._guard_practice(worst_revert_domain)

        # 5) Autonomy recommendations from the calibrator.
        try:
            result.autonomy_recommendations = self.calibrator.recommendations()
        except Exception:
            result.autonomy_recommendations = {}

        # 6) Fold tightened 'ask_when' rules into a new profile version if the
        #    signal is meaningful; always advance _last_learn_ts.
        low_domains = []
        for domain, stats in sorted(calib.items()):
            total = int((stats or {}).get("total", 0) or 0)
            rate = float((stats or {}).get("rate", 0.0) or 0.0)
            if total >= ASK_WHEN_MIN_SAMPLES and rate < ASK_WHEN_RATE:
                low_domains.append(domain)
        # 'meaningful new signal' = we recorded calibration, OR we found drift /
        # low domains worth writing a rule for.
        meaningful = recorded > 0 or bool(drift) or bool(low_domains)

        prof["_last_learn_ts"] = now
        if meaningful:
            self._merge_ask_when(prof, low_domains, revert_counts)
            try:
                version = self.store.save_operator_profile(
                    json.dumps(prof), source="learned",
                    model=self.model or "",
                )
                result.profile_version = int(version)
            except Exception:
                result.profile_version = -1
        else:
            # No signal: still persist the advanced watermark so we stay idempotent.
            try:
                self.store.save_operator_profile(
                    json.dumps(prof), source="learned", model=self.model or "",
                )
            except Exception:
                pass
            result.profile_version = -1

        return result

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _ts(row: dict, key: str) -> float:
        try:
            return float(row.get(key) or 0.0)
        except Exception:
            return 0.0

    def _merge_ask_when(self, prof: dict, low_domains: list[str],
                        revert_counts: dict[str, int]) -> None:
        """Append/merge 'ask_when' entries for domains whose rate dropped low or
        that keep getting reverted. De-duped, order-preserving."""
        ask = prof.get("ask_when")
        if not isinstance(ask, list):
            ask = [str(x) for x in ask] if ask else []
        targets = list(low_domains)
        for domain, n in revert_counts.items():
            if n >= REVERT_DRIFT_THRESHOLD and domain not in targets:
                targets.append(domain)
        for domain in targets:
            rule = (f"Stop and ask before acting on '{domain}' — recent signal shows "
                    f"the clone gets this wrong; confirm with the user first.")
            if rule not in ask:
                ask.append(rule)
        prof["ask_when"] = ask

    def _guard_practice(self, domain: str) -> str:
        """A concrete guarding practice for a repeatedly-reverted domain. Uses the
        local LLM to phrase it nicely IF available and a model was requested;
        otherwise the deterministic library entry."""
        base = _GUARD_PRACTICES.get(
            domain.lower(),
            f"Add an explicit verification step for '{domain}' changes before "
            f"committing — the clone keeps getting reverted here.",
        )
        if not self.model:
            return base
        try:
            from sentigent.intelligence import local_llm
            if not local_llm.llm_available():
                return base
            prompt = (
                f"In one short imperative sentence, state a guarding best-practice "
                f"for '{domain}' work that would prevent the kind of mistake that "
                f"gets reverted. Base it on: {base}"
            )
            out = local_llm.generate(prompt, model=self.model, timeout=20.0).strip()
            return out.splitlines()[0].strip() if out else base
        except Exception:
            return base
