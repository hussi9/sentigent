#!/usr/bin/env python3
"""Experiment E2 — does the judgment layer improve real coding-task completion?

The decisive, world-correctness test E1 could not give (E1 proved learnability on the
engine's own labels; this measures *resolved real bugs*). Runs SWE-bench Verified as an
A/B:

  arm "baseline"  : plain `claude -p` solves the instance
  arm "layer"     : `claude -p` WITH the Sentigent MCP + hooks active (RiskAssessor,
                    escalation, verifier, self-repair)

For each instance × arm: clone the repo at base_commit, let the agent edit it, capture
`git diff` as the model patch, write SWE-bench predictions jsonl, then score with the
OFFICIAL swebench Docker harness. Headline = resolved-rate delta (and VACR: resolved AND
no escalation-flagged abort).

COST/INFRA: prediction generation spends Claude tokens; evaluation needs Docker + ~2-4GB
per instance image. `--dry-run` validates the full pipeline (clone + patch capture +
prediction format) with a stub agent — zero tokens, zero Docker — so the harness is proven
before any spend.

Run:
  # prove the wiring, free:
  .venv/bin/python3 training/eval/swebench_ab.py --dry-run --n 1
  # real run (tokens + Docker), e.g. on the Mac Mini or once disk is freed:
  .venv/bin/python3 training/eval/swebench_ab.py --n 25 --arms baseline layer --evaluate
"""
from __future__ import annotations

import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

DATASET = "princeton-nlp/SWE-bench_Verified"
HERE = Path(__file__).parent
OUT = HERE / "swebench_out"
CLAUDE = os.environ.get("CLAUDE_BIN", "claude")
# lighter repos → smaller images → smoke-friendly on a tight disk
LIGHT_REPOS = ["psf/requests", "pylint-dev/pylint", "pytest-dev/pytest", "sphinx-doc/sphinx"]


def pick_instances(n: int, light_first: bool, only=None):
    from datasets import load_dataset
    ds = load_dataset(DATASET, split="test")
    rows = list(ds)
    if only:
        rows = [r for r in rows if r["instance_id"] in set(only)]
    elif light_first:
        rows.sort(key=lambda r: (r["repo"] not in LIGHT_REPOS, r["repo"]))
    return rows[:n]


def clone_at(repo: str, base_commit: str, dest: Path):
    url = f"https://github.com/{repo}.git"
    subprocess.run(["git", "clone", "--quiet", url, str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", base_commit], check=True)


def agent_patch(repo_dir: Path, instance: dict, arm: str, timeout: int) -> str:
    """Run the agent in repo_dir; return the git diff it produced (the model patch)."""
    prompt = (
        "You are fixing a real bug in this repository. Resolve the issue below by editing "
        "the source. Do NOT edit tests. When done, stop.\n\n"
        f"ISSUE:\n{instance['problem_statement']}\n"
    )
    cmd = [CLAUDE, "-p", prompt, "--output-format", "json", "--dangerously-skip-permissions"]
    if arm == "layer":
        # layer arm: Sentigent MCP + hooks active (project .mcp.json / settings provide them).
        # baseline arm explicitly disables them for a clean control.
        env = os.environ.copy()
    else:
        env = os.environ.copy()
        env["SENTIGENT_DISABLED"] = "1"  # control: judgment layer off
    try:
        subprocess.run(cmd, cwd=str(repo_dir), env=env, timeout=timeout,
                       capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        pass
    diff = subprocess.run(["git", "-C", str(repo_dir), "diff"], capture_output=True, text=True)
    return diff.stdout


def stub_patch(repo_dir: Path, instance: dict) -> str:
    """Dry-run: make a trivial no-op edit so we exercise diff capture + prediction format."""
    marker = repo_dir / ".sentigent_dryrun"
    marker.write_text("dry-run prediction placeholder\n")
    subprocess.run(["git", "-C", str(repo_dir), "add", "-A"], check=True)
    return subprocess.run(["git", "-C", str(repo_dir), "diff", "--cached"],
                          capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--arms", nargs="+", default=["baseline", "layer"])
    ap.add_argument("--instances", nargs="*", help="explicit instance_ids")
    ap.add_argument("--timeout", type=int, default=900, help="per-instance agent seconds")
    ap.add_argument("--dry-run", action="store_true", help="stub agent, no tokens/Docker")
    ap.add_argument("--evaluate", action="store_true", help="run official Docker scoring")
    ap.add_argument("--light-first", action="store_true", default=True)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    instances = pick_instances(args.n, args.light_first, args.instances)
    print(f"E2 SWE-bench A/B — {len(instances)} instance(s), arms={args.arms}, "
          f"{'DRY-RUN' if args.dry_run else 'LIVE'}")
    for i in instances:
        print(f"  • {i['instance_id']}  ({i['repo']})")

    pred_paths = {}
    for arm in args.arms:
        preds = []
        for inst in instances:
            work = Path(tempfile.mkdtemp(prefix=f"swe_{arm}_"))
            repo_dir = work / "repo"
            try:
                clone_at(inst["repo"], inst["base_commit"], repo_dir)
                patch = (stub_patch(repo_dir, inst) if args.dry_run
                         else agent_patch(repo_dir, inst, arm, args.timeout))
                preds.append({"instance_id": inst["instance_id"],
                              "model_name_or_path": f"sentigent-{arm}",
                              "model_patch": patch})
                print(f"  [{arm}] {inst['instance_id']}: patch {len(patch)} chars")
            except subprocess.CalledProcessError as e:
                print(f"  [{arm}] {inst['instance_id']}: CLONE/SETUP FAILED ({e})")
                preds.append({"instance_id": inst["instance_id"],
                              "model_name_or_path": f"sentigent-{arm}", "model_patch": ""})
            finally:
                shutil.rmtree(work, ignore_errors=True)  # reclaim disk immediately
        p = OUT / f"preds_{arm}.jsonl"
        p.write_text("\n".join(json.dumps(x) for x in preds))
        pred_paths[arm] = p
        print(f"  → wrote {p}")

    if args.dry_run:
        print("\nDRY-RUN OK ✅  pipeline (select → clone → patch → predictions) wired.")
        print("Predictions are placeholders; no tokens spent, no Docker used.")
        print("Fire the real run with: --n 25 --arms baseline layer --evaluate  (needs Docker + disk)")
        return

    if not args.evaluate:
        print("\nPredictions generated. Re-run with --evaluate (Docker) to score, or score on a host with disk.")
        return

    # Official Docker evaluation, per arm.
    if shutil.which("docker") is None:
        raise SystemExit("docker not found — cannot evaluate. Run on a host with Docker + disk.")
    for arm, p in pred_paths.items():
        run_id = f"sentigent_{arm}"
        print(f"\n── evaluating arm={arm} via swebench Docker harness ──")
        subprocess.run([sys.executable, "-m", "swebench.harness.run_evaluation",
                        "--dataset_name", DATASET, "--predictions_path", str(p),
                        "--run_id", run_id, "--max_workers", "2", "--cache_level", "instance"],
                       check=False)
        print(f"  → see {arm}.{run_id}.json report for resolved count")
    print("\nHeadline = resolved-rate(layer) − resolved-rate(baseline). Compare the two reports.")


if __name__ == "__main__":
    main()
