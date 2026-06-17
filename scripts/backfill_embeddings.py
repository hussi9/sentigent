#!/usr/bin/env python3
"""Backfill Layer-2 episode embeddings so semantic recall works on already-synced rows.

Phase 5 added an `embedding vector(384)` column to Supabase `synced_episodes`, and the
push path embeds new rows — but rows synced before that have `embedding IS NULL`, so
semantic search can't find them. This selects null-embedding rows, encodes their task
text with the local embedder, and writes the vectors back.

    python scripts/backfill_embeddings.py            # backfill (idempotent, safe to re-run)
    python scripts/backfill_embeddings.py --dry-run  # count what's missing, write nothing
    python scripts/backfill_embeddings.py --limit 500

Requires Supabase env (SUPABASE_URL + service key) and sentence-transformers. Fail-soft:
if either is missing it tells you plainly and exits 0 — it never crashes a pipeline.
"""
from __future__ import annotations

import json
import os
import sys


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    limit = 1000
    if "--limit" in argv:
        try:
            limit = int(argv[argv.index("--limit") + 1])
        except (ValueError, IndexError):
            pass

    # 1) embedder (local, free) — fail-soft
    try:
        from sentigent.core.embedder import get_embedder
        embedder = get_embedder()
    except Exception as e:
        embedder = None
    if embedder is None:
        print(json.dumps({"ok": False, "reason": "embedder unavailable "
                          "(install sentence-transformers)", "updated": 0}))
        return 0

    # 2) Supabase client — fail-soft
    try:
        from sentigent.sync.manager import _get_supabase_client
        client = _get_supabase_client()
    except Exception as e:
        print(json.dumps({"ok": False, "reason": f"supabase unavailable ({e})",
                          "updated": 0}))
        return 0

    # 3) fetch rows missing an embedding
    try:
        resp = (client.table("synced_episodes")
                .select("id, trace_id, task")
                .is_("embedding", "null")
                .limit(limit)
                .execute())
        rows = resp.data or []
    except Exception as e:
        print(json.dumps({"ok": False, "reason": f"query failed ({e})", "updated": 0}))
        return 0

    missing = len(rows)
    if dry or not rows:
        print(json.dumps({"ok": True, "dry_run": dry, "missing": missing,
                          "updated": 0, "note": "run without --dry-run to backfill"}))
        return 0

    # 4) encode in batch + write back, one row at a time (idempotent)
    texts = [str(r.get("task") or "") for r in rows]
    try:
        vecs = embedder.encode_batch(texts)
    except Exception as e:
        print(json.dumps({"ok": False, "reason": f"encode failed ({e})", "updated": 0}))
        return 0

    updated = 0
    for r, vec in zip(rows, vecs):
        if not vec:
            continue
        try:
            client.table("synced_episodes").update({"embedding": list(vec)}) \
                  .eq("id", r["id"]).execute()
            updated += 1
        except Exception:
            continue

    print(json.dumps({"ok": True, "dry_run": False, "missing": missing,
                      "updated": updated}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
