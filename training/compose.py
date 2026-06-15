#!/usr/bin/env python3
"""Compose the EFFECTIVE ruleset = baseline principles + opt-in practice packs.

  python training/compose.py --packs tdd security-first

Semantics:
  - start from training/principles.yaml (the baseline floor)
  - for each pack (training/packs/<id>.yaml), in order:
      * override: merge fields onto an existing principle by id
      * add:      append new principles (error on id collision unless overridden)
  - every rule carries `_source` provenance (baseline | pack:<id>)
  - a pack may NOT downgrade a `personalizable: false` safety rule to true
    (the floor is locked — packs adjust, they don't weaken safety).

Output: training/data/effective_ruleset.{yaml,json} + a printed summary.
Pure local, no deps beyond PyYAML.
"""
from __future__ import annotations

import argparse, json
from pathlib import Path

try:
    import yaml
except ImportError:
    raise SystemExit("pip install pyyaml")

HERE = Path(__file__).parent


def _load(p: Path) -> dict:
    return yaml.safe_load(p.read_text()) or {}


def compose(pack_ids: list[str]) -> dict:
    base = _load(HERE / "principles.yaml")
    rules: dict[str, dict] = {}
    for pr in base.get("principles", []):
        pr = dict(pr)
        pr["_source"] = "baseline"
        rules[pr["id"]] = pr

    applied = []
    for pid in pack_ids:
        pack = _load(HERE / "packs" / f"{pid}.yaml")
        if not pack:
            raise SystemExit(f"pack not found: {pid}")
        for rid, fields in (pack.get("override") or {}).items():
            if rid not in rules:
                raise SystemExit(f"pack {pid} overrides unknown principle {rid}")
            tgt = rules[rid]
            # Locked-floor guard: a pack can tighten, never weaken a safety rule.
            if tgt.get("personalizable") is False and fields.get("personalizable") is True:
                raise SystemExit(f"pack {pid} may not unlock safety rule {rid}")
            tgt.update(fields)
            tgt["_source"] = f"{tgt['_source']}+pack:{pid}"
        for pr in (pack.get("add") or []):
            pr = dict(pr)
            if pr["id"] in rules:
                raise SystemExit(f"pack {pid} adds duplicate id {pr['id']} (use override)")
            pr["_source"] = f"pack:{pid}"
            rules[pr["id"]] = pr
        applied.append(pid)

    eff = list(rules.values())
    return {
        "baseline": "principles.yaml",
        "packs_applied": applied,
        "rule_count": len(eff),
        "hard": sum(1 for r in eff if r.get("severity") == "hard"),
        "soft": sum(1 for r in eff if r.get("severity") == "soft"),
        "personalizable": sum(1 for r in eff if r.get("personalizable")),
        "from_packs": sum(1 for r in eff if r["_source"] != "baseline"),
        "rules": eff,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", nargs="*", default=[])
    ap.add_argument("--out", default=str(HERE / "data"))
    args = ap.parse_args()
    result = compose(args.packs)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "effective_ruleset.json").write_text(json.dumps(result, indent=2))
    (out / "effective_ruleset.yaml").write_text(yaml.safe_dump(result, sort_keys=False))

    summary = {k: v for k, v in result.items() if k != "rules"}
    print(json.dumps(summary, indent=2))
    print(f"\n→ {len(result['rules'])} effective rules written to {out}/effective_ruleset.*")


if __name__ == "__main__":
    main()
