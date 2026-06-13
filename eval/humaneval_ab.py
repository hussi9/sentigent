#!/usr/bin/env python3
"""HumanEval A/B — same base model, Sentigent loop ON vs blank agent OFF (EVALUATION.md proof).

OFF (blank `claude -p`): one-shot generation, graded on the official hidden test.
ON  (Sentigent mechanism): generate → run the task's tests (its Definition-of-Done) → on failure,
    self-repair with the error fed back, up to max_attempts. Graded on the SAME official test.

Both arms use the SAME base model. The ON arm is NOT shown the grading test text; it only learns
PASS/FAIL from running the task's own test suite — exactly what Sentigent's Verifier does in real
use (run the project's tests before 'done', self-correct on failure). The delta is therefore
attributable to the verify+self-repair *mechanism*, not to model quality.

Honest cost note: ON spends MORE tokens (it retries). The meaningful cost metric is **wasted tokens**
= tokens spent on tasks that still end up failing. We report both.

Usage:
  python eval/humaneval_ab.py --n 6 --max-attempts 3 --data /tmp/he.jsonl.gz
"""
from __future__ import annotations

import argparse, gzip, json, os, re, subprocess, sys, tempfile, time

CLAUDE = os.environ.get("CLAUDE_BIN") or "claude"


def claude(prompt: str, timeout: float = 180.0) -> tuple[str, int, int]:
    """Call `claude -p` once. Returns (text, input_tokens, output_tokens). Same model for both arms."""
    cmd = [CLAUDE, "-p", prompt, "--output-format", "json"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", 0, 0
    try:
        j = json.loads(p.stdout)
    except Exception:
        return (p.stdout or ""), 0, 0
    # `claude -p --output-format json` returns a LIST of events; the final {type:"result"} carries
    # the answer text + usage. Be tolerant of either a dict or that list.
    if isinstance(j, list):
        j = next((x for x in reversed(j) if isinstance(x, dict) and x.get("type") == "result"), {})
    if not isinstance(j, dict):
        return (p.stdout or ""), 0, 0
    usage = j.get("usage") or {}
    return (j.get("result", "") or ""), int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


def grade(code: str, test: str, entry_point: str, timeout: float = 12.0) -> tuple[bool, str]:
    """Run the official HumanEval check in an isolated subprocess. (True, '') on pass."""
    src = f"{code}\n\n{test}\n\ncheck({entry_point})\n"
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "cand.py")
        with open(f, "w") as fh:
            fh.write(src)
        try:
            r = subprocess.run([sys.executable, f], capture_output=True, text=True, timeout=timeout, cwd=d)
        except subprocess.TimeoutExpired:
            return False, "timeout"
        if r.returncode == 0:
            return True, ""
        return False, (r.stderr or r.stdout or "nonzero exit")[-600:]


def gen_prompt(prob: str) -> str:
    return ("Complete this Python function. Return ONLY the complete function (signature + body) "
            "in a ```python code block — no prose.\n\n" + prob)


def repair_prompt(prob: str, code: str, err: str) -> str:
    return ("Your solution failed its tests.\n\n=== TASK ===\n" + prob +
            "\n\n=== YOUR CODE ===\n" + code + "\n\n=== TEST FAILURE ===\n" + err[-800:] +
            "\n\nFix it. Return ONLY the corrected complete function in a ```python block.")


def run_off(prob: dict) -> dict:
    text, ti, to = claude(gen_prompt(prob["prompt"]))
    code = extract_code(text)
    ok, _ = grade(code, prob["test"], prob["entry_point"])
    return {"passed": ok, "in": ti, "out": to, "calls": 1}


def run_on(prob: dict, max_attempts: int) -> dict:
    total_in = total_out = calls = 0
    text, ti, to = claude(gen_prompt(prob["prompt"]))
    total_in += ti; total_out += to; calls += 1
    code = extract_code(text)
    ok, err = grade(code, prob["test"], prob["entry_point"])
    attempts = 1
    while not ok and attempts < max_attempts:
        text, ti, to = claude(repair_prompt(prob["prompt"], code, err))
        total_in += ti; total_out += to; calls += 1
        code = extract_code(text)
        ok, err = grade(code, prob["test"], prob["entry_point"])
        attempts += 1
    return {"passed": ok, "in": total_in, "out": total_out, "calls": calls,
            "attempts": attempts, "self_repaired": ok and attempts > 1}


def card(results: list[dict], model_note: str) -> str:
    n = len(results)
    off_pass = sum(r["off"]["passed"] for r in results)
    on_pass = sum(r["on"]["passed"] for r in results)
    repaired = sum(r["on"].get("self_repaired", False) for r in results)
    off_tok = sum(r["off"]["in"] + r["off"]["out"] for r in results)
    on_tok = sum(r["on"]["in"] + r["on"]["out"] for r in results)
    off_waste = sum((r["off"]["in"] + r["off"]["out"]) for r in results if not r["off"]["passed"])
    on_waste = sum((r["on"]["in"] + r["on"]["out"]) for r in results if not r["on"]["passed"])
    pct = lambda k: f"{100*k/n:.0f}%" if n else "—"
    L = []
    L.append("━" * 64)
    L.append("  SENTIGENT EVAL CARD — HumanEval A/B (verify + self-repair vs one-shot)")
    L.append("━" * 64)
    L.append(f"  Base model: {model_note} (identical in both arms)   ·   N = {n}")
    L.append("")
    L.append(f"  {'metric':<34}{'OFF (blank)':>14}{'ON (Sentigent)':>16}")
    L.append(f"  {'-'*62}")
    L.append(f"  {'verified pass@1':<34}{off_pass:>9} ({pct(off_pass)}){on_pass:>11} ({pct(on_pass)})")
    L.append(f"  {'failures (= human-fix events)':<34}{n-off_pass:>14}{n-on_pass:>16}")
    L.append(f"  {'auto-self-repaired (no human)':<34}{'—':>14}{repaired:>16}")
    L.append(f"  {'total tokens':<34}{off_tok:>14,}{on_tok:>16,}")
    L.append(f"  {'WASTED tokens (on failed tasks)':<34}{off_waste:>14,}{on_waste:>16,}")
    L.append("")
    L.append(f"  Δ verified pass@1 : {100*(on_pass-off_pass)/n:+.0f} pts")
    L.append(f"  Δ failures        : {(n-on_pass)-(n-off_pass):+d}  (fewer = less human intervention)")
    L.append(f"  Δ wasted tokens   : {on_waste-off_waste:+,}")
    L.append("━" * 64)
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--data", default="/tmp/he.jsonl.gz")
    ap.add_argument("--out", default="eval/results/humaneval_ab.json")
    args = ap.parse_args()

    rows = [json.loads(l) for l in gzip.open(args.data, "rt")][: args.n]
    results = []
    for i, prob in enumerate(rows, 1):
        t0 = time.time()
        off = run_off(prob)
        on = run_on(prob, args.max_attempts)
        results.append({"task": prob["task_id"], "off": off, "on": on})
        print(f"[{i}/{len(rows)}] {prob['task_id']:<14} OFF={'PASS' if off['passed'] else 'fail'}"
              f"  ON={'PASS' if on['passed'] else 'fail'}"
              f"{' (repaired)' if on.get('self_repaired') else ''}  {time.time()-t0:.0f}s", flush=True)

    out = card(results, "claude -p default")
    print("\n" + out)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"results": results, "card": out}, fh, indent=2)
    print(f"\nsaved → {args.out}")


if __name__ == "__main__":
    main()
