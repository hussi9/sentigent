#!/usr/bin/env python3
"""build_profile.py — synthesize + persist the operator profile.

The first user-facing sentigent intelligence command. Reads your CLAUDE.md
(explicit) + the captured decision_events signal (implicit), runs a local LLM
(Ollama, model-agnostic), and writes a versioned operator_profile row.

Usage:
    python3 scripts/build_profile.py                 # default model (env or llama3:8b)
    SENTIGENT_LLM_MODEL=gemma3:27b python3 scripts/build_profile.py   # switch to Gemma
    python3 scripts/build_profile.py --show          # just print the latest stored profile
    python3 scripts/build_profile.py --agent hussain # pick the agent store

No cloud calls. Fail-soft: if Ollama is down, writes an `explicit_only` profile
rather than inventing one.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running from repo root without install.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sentigent.core.profile_builder import ProfileBuilder  # noqa: E402
from sentigent.intelligence import local_llm  # noqa: E402
from sentigent.memory.store import MemoryStore  # noqa: E402

DEFAULT_AGENT = os.environ.get("SENTIGENT_AGENT_ID", "hussain")
DEFAULT_ORG = os.environ.get("SENTIGENT_ORG_ID", "hussain")


def _store(agent: str) -> MemoryStore:
    return MemoryStore(agent_id=agent, org_id=DEFAULT_ORG)


def main() -> int:
    ap = argparse.ArgumentParser(description="Synthesize the operator profile.")
    ap.add_argument("--agent", default=DEFAULT_AGENT, help="agent_id store to use")
    ap.add_argument("--model", default=None, help="override SENTIGENT_LLM_MODEL")
    ap.add_argument("--claude-md", default=None, help="path to CLAUDE.md")
    ap.add_argument("--show", action="store_true", help="print latest stored profile and exit")
    args = ap.parse_args()

    store = _store(args.agent)

    if args.show:
        latest = store.get_latest_operator_profile()
        if not latest:
            print("No operator profile stored yet. Run without --show to build one.")
            return 0
        print(f"# operator_profile v{latest['version']} "
              f"(source={latest['source']}, model={latest['model']})")
        print(json.dumps(json.loads(latest["profile_json"]), indent=2))
        return 0

    available = local_llm.llm_available()
    model = args.model or local_llm.active_model()
    present = local_llm.list_models()
    print(f"local LLM reachable: {available} | model: {model} | pulled: {present or '[]'}")
    if available and model not in present:
        print(f"  note: '{model}' not pulled yet — Ollama will error; "
              f"falling back to explicit_only or pick a pulled model.")

    builder = ProfileBuilder(
        store=store, agent_id=args.agent, claude_md_path=args.claude_md, model=model
    )
    profile = builder.build()

    print(f"\n# built operator_profile v{profile['version']} (source={profile['source']})")
    print(json.dumps(profile, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
