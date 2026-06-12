"""ProfileReview — Step 2 of the clone lifecycle: review the clone honestly.

Benchmarks the operator profile + declared practices against the best-practices KB
(universal + organizational) and produces four buckets:

  • GOOD       — strengths to keep (best practices you already embody)
  • BAD        — traits/tensions working AGAINST a best practice (LLM-reasoned)
  • GAPS       — important best practices you're missing → each ADOPTABLE as a
                 practice (this is Step 3: improve the clone)
  • coverage   — share of high-importance universal practices you cover

Deterministic gap detection is the reliable backbone; the local LLM enriches the
GOOD/BAD qualitative read. Fail-soft: with no LLM, you still get coverage + gaps.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from sentigent.intelligence import local_llm
from sentigent.operator import best_practices as bp


@dataclass
class ReviewItem:
    text: str
    why: str = ""
    domain: str = "global"

    def to_dict(self) -> dict:
        return {"text": self.text, "why": self.why, "domain": self.domain}


@dataclass
class Gap:
    key: str
    domain: str
    statement: str
    rationale: str
    importance: str
    cadence: str

    def to_dict(self) -> dict:
        return {"key": self.key, "domain": self.domain, "statement": self.statement,
                "rationale": self.rationale, "importance": self.importance, "cadence": self.cadence}


@dataclass
class ProfileReview:
    good: list[ReviewItem] = field(default_factory=list)
    bad: list[ReviewItem] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    coverage_pct: int = 0
    source: str = "deterministic"   # llm | deterministic
    profile_source: str = "none"

    def to_dict(self) -> dict:
        return {
            "coverage_pct": self.coverage_pct,
            "source": self.source,
            "profile_source": self.profile_source,
            "good": [i.to_dict() for i in self.good],
            "bad": [i.to_dict() for i in self.bad],
            "gaps": [g.to_dict() for g in self.gaps],
        }


_SYSTEM = (
    "You are a staff engineer reviewing a teammate's working profile. Be candid but "
    "constructive: name genuine strengths AND real anti-patterns. Judge only from the "
    "profile text and the best-practice list given. Output STRICT JSON."
)

_SCHEMA = """Return ONLY this JSON:
{
  "good": [{"text": "<a real strength, in plain language>", "why": "<why it's good>"}],
  "bad":  [{"text": "<a trait that works AGAINST good practice>", "why": "<the risk it creates>"}]
}
Focus 'bad' on genuine tensions (e.g. 'always execute without pausing' vs 'confirm before
destructive actions'). 2-5 items each. Do not invent traits not present in the profile."""


def _profile_text(profile: dict, practices: list[dict]) -> str:
    parts: list[str] = [str(profile.get("summary", ""))]
    for k in ("preferences", "coding_standards", "never_do", "ask_when"):
        for v in profile.get(k) or []:
            parts.append(str(v))
    for pr in practices:
        parts.append(str(pr.get("text", "")))
    return "\n".join(p for p in parts if p)


def _gaps_and_covered(text: str, kb: list[bp.Practice]) -> tuple[list[Gap], list[bp.Practice]]:
    gaps, covered = [], []
    for p in kb:
        if p.covered_by(text):
            covered.append(p)
        else:
            gaps.append(Gap(p.key, p.domain, p.statement, p.rationale, p.importance, p.cadence))
    # surface the most important gaps first
    rank = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: rank.get(g.importance, 3))
    return gaps, covered


def review(store: Any, model: Optional[str] = None, include_org: bool = True,
           use_llm: bool = True) -> ProfileReview:
    """Produce a review of the stored profile. Never raises.

    use_llm=False skips the LLM good/bad enrichment and returns the deterministic
    backbone only (coverage + gaps + covered-practice strengths). Use that on
    latency-sensitive paths like the SessionStart briefing."""
    profile: dict = {}
    psource = "none"
    try:
        latest = store.get_latest_operator_profile()
        if latest:
            profile = json.loads(latest.get("profile_json", "{}"))
            psource = latest.get("source", "none")
    except Exception:
        pass
    try:
        practices = store.get_practices(active_only=True)
    except Exception:
        practices = []

    kb = bp.all_practices(include_org=include_org)
    text = _profile_text(profile, practices)
    gaps, covered = _gaps_and_covered(text, kb)

    # coverage over HIGH-importance universal practices (the ones that really matter)
    high = [p for p in kb if p.importance == "high"]
    high_covered = [p for p in covered if p.importance == "high"]
    coverage_pct = int(round(100 * len(high_covered) / len(high))) if high else 0

    # GOOD backbone: the high/medium practices you already cover.
    good = [ReviewItem(p.statement, p.rationale, p.domain)
            for p in covered if p.importance in ("high", "medium")]

    out = ProfileReview(good=good, bad=[], gaps=gaps, coverage_pct=coverage_pct,
                        source="deterministic", profile_source=psource)

    # LLM enrichment of GOOD/BAD (qualitative read of the actual profile).
    if use_llm and text.strip() and local_llm.llm_available():
        kb_summary = "; ".join(f"{p.domain}: {p.statement}" for p in kb)
        prompt = (
            f"{_SCHEMA}\n\n=== THE ENGINEER'S PROFILE ===\n{text[:6000]}\n\n"
            f"=== BEST PRACTICES TO JUDGE AGAINST ===\n{kb_summary}\n"
        )
        raw = local_llm.generate_json(prompt, model=model, system=_SYSTEM)
        if isinstance(raw, dict):
            llm_good = [ReviewItem(str(d.get("text", "")), str(d.get("why", "")))
                        for d in (raw.get("good") or []) if isinstance(d, dict) and d.get("text")]
            llm_bad = [ReviewItem(str(d.get("text", "")), str(d.get("why", "")))
                       for d in (raw.get("bad") or []) if isinstance(d, dict) and d.get("text")]
            if llm_good or llm_bad:
                # LLM strengths lead; dedupe the deterministic 'good' behind them.
                out.good = llm_good + good
                out.bad = llm_bad
                out.source = "llm"
    return out
