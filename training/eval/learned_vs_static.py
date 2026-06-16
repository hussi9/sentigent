#!/usr/bin/env python3
"""Experiment E1 — does learned judgment beat a static rubric? (offline, local, free)

See training/EXPERIMENT.md for the falsifiable design. Tests four predictors on a
time-ordered held-out split of the operator's own decision history:

  B0  constant 'proceed'                      (floor)
  B1  static rubric (fixed signal thresholds) (the hand-written-policy bar to beat)
  L1  kNN over the 5-dim signal vector        (learning from similar situations)
  L2  kNN over signals + TF-IDF(task text)    (learning from situation + content)

Headline = balanced accuracy + minority-class recall (proceed is 96% of the data, so
aggregate accuracy is a lie). Decision rule printed at the end.

No network, no model download — TF-IDF + kNN are fully local. Run:
  .venv/bin/python3 training/eval/learned_vs_static.py --agent hussain
"""
from __future__ import annotations

import argparse, json, sqlite3, sys
from collections import Counter
from pathlib import Path

import numpy as np

try:
    from scipy.sparse import hstack, csr_matrix
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import NearestNeighbors
    from sklearn.metrics import balanced_accuracy_score, recall_score, confusion_matrix
    from sklearn.preprocessing import StandardScaler
except ImportError as e:
    raise SystemExit(f"needs scikit-learn + scipy ({e})")

CLASSES = ["proceed", "enrich", "slow_down", "escalate"]
MINORITY = ["enrich", "slow_down", "escalate"]
SIGNAL_KEYS = ["caution", "doubt", "urgency", "confidence", "frustration"]


def _j(s):
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {}


def load(agent: str, db_dir: str):
    db = Path(db_dir) / f"memory_{agent}.db"
    if not db.exists():
        raise SystemExit(f"no brain at {db}")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute(
        "SELECT timestamp, task, context, signals, decision FROM episodes "
        "WHERE decision IN (?,?,?,?) AND signals!='' ORDER BY timestamp ASC",
        CLASSES,
    ).fetchall()
    sig, txt, lab = [], [], []
    for ts, task, ctx, signals, decision in rows:
        s = _j(signals)
        if not s:
            continue
        sig.append([float(s.get(k, 0.0) or 0.0) for k in SIGNAL_KEYS])
        txt.append(f"{task or ''} {(_j(ctx).get('tool_name',''))}")
        lab.append(decision)
    return np.array(sig, float), txt, np.array(lab)


# ── B1: static rubric (the hand-written-policy bar) ───────────────────────────
def rubric(sig: np.ndarray) -> np.ndarray:
    caution, doubt, urgency, confidence, frustration = (sig[:, i] for i in range(5))
    out = np.full(sig.shape[0], "proceed", dtype=object)
    out[(doubt >= 0.5) | (confidence <= 0.4)] = "enrich"
    out[caution >= 0.5] = "slow_down"
    out[caution >= 0.8] = "escalate"
    return out


# ── kNN learned predictors ────────────────────────────────────────────────────
def knn_predict(Xtr, ytr, Xte, k: int) -> np.ndarray:
    nn = NearestNeighbors(n_neighbors=min(k, Xtr.shape[0]), metric="cosine").fit(Xtr)
    _, idx = nn.kneighbors(Xte)
    preds = []
    for nbrs in idx:
        preds.append(Counter(ytr[nbrs]).most_common(1)[0][0])
    return np.array(preds, dtype=object)


def report(name: str, y_true, y_pred) -> dict:
    ba = balanced_accuracy_score(y_true, y_pred)
    rec = recall_score(y_true, y_pred, labels=MINORITY, average="macro", zero_division=0)
    agg = float((y_true == y_pred).mean())
    per = recall_score(y_true, y_pred, labels=CLASSES, average=None, zero_division=0)
    return {"name": name, "bal_acc": ba, "minority_recall": rec, "aggregate": agg,
            "per_class": dict(zip(CLASSES, [round(float(x), 3) for x in per]))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="hussain")
    ap.add_argument("--db", default=str(Path.home() / ".sentigent"))
    ap.add_argument("--k", type=int, default=15)
    ap.add_argument("--cap-train", type=int, default=40000)  # kNN fit speed
    ap.add_argument("--cap-test", type=int, default=6000)
    args = ap.parse_args()

    sig, txt, lab = load(args.agent, args.db)
    n = len(lab)
    if n < 200:
        raise SystemExit(f"too few labeled episodes ({n}) for a meaningful split")

    split = int(n * 0.8)
    tr, te = slice(0, split), slice(split, n)
    sig_tr, sig_te = sig[tr], sig[te]
    txt_tr, txt_te = txt[:split], txt[split:]
    y_tr, y_te = lab[tr], lab[te]

    # cap for speed (keep time order: tail of train, head-sample of test)
    if sig_tr.shape[0] > args.cap_train:
        sig_tr = sig_tr[-args.cap_train:]; y_tr = y_tr[-args.cap_train:]
        txt_tr = txt_tr[-args.cap_train:]
    if sig_te.shape[0] > args.cap_test:
        step = sig_te.shape[0] // args.cap_test
        sig_te = sig_te[::step][:args.cap_test]; y_te = y_te[::step][:args.cap_test]
        txt_te = txt_te[::step][:args.cap_test]

    print("━" * 70)
    print("  EXPERIMENT E1 — learned judgment vs static rubric (held-out, time-split)")
    print("━" * 70)
    print(f"  agent={args.agent}  total={n}  train={len(y_tr)}  test={len(y_te)}  k={args.k}")
    print(f"  test decision mix: {dict(Counter(y_te))}")

    results = []
    # B0 constant
    results.append(report("B0 constant-proceed", y_te, np.full(len(y_te), "proceed", dtype=object)))
    # B1 static rubric
    results.append(report("B1 static-rubric", y_te, rubric(sig_te)))
    # L1 kNN on signals (standardized)
    sc = StandardScaler().fit(sig_tr)
    results.append(report("L1 learned-kNN(signals)", y_te,
                          knn_predict(sc.transform(sig_tr), y_tr, sc.transform(sig_te), args.k)))
    # L2 kNN on signals + TF-IDF(task)
    vec = TfidfVectorizer(max_features=4000, ngram_range=(1, 2), min_df=2)
    Xtr_txt = vec.fit_transform(txt_tr); Xte_txt = vec.transform(txt_te)
    Xtr = hstack([csr_matrix(sc.transform(sig_tr)), Xtr_txt]).tocsr()
    Xte = hstack([csr_matrix(sc.transform(sig_te)), Xte_txt]).tocsr()
    results.append(report("L2 learned-kNN(sig+text)", y_te, knn_predict(Xtr, y_tr, Xte, args.k)))

    # ── table ──
    print("\n  {:<28}{:>9}{:>11}{:>11}".format("condition", "bal_acc", "min_rec", "aggregate"))
    print("  " + "─" * 58)
    for r in results:
        print("  {:<28}{:>9.3f}{:>11.3f}{:>11.3f}".format(
            r["name"], r["bal_acc"], r["minority_recall"], r["aggregate"]))
    print("\n  per-class recall (proceed / enrich / slow_down / escalate):")
    for r in results:
        print(f"    {r['name']:<28} {r['per_class']}")

    # ── verdict ──
    b1 = next(r for r in results if r["name"].startswith("B1"))
    best_learned = max((r for r in results if r["name"].startswith("L")), key=lambda r: r["bal_acc"])
    delta = best_learned["bal_acc"] - b1["bal_acc"]
    min_delta = best_learned["minority_recall"] - b1["minority_recall"]
    print("\n" + "━" * 70)
    print(f"  HEADLINE: best learned ({best_learned['name']}) − static rubric (B1)")
    print(f"    Δ balanced_accuracy : {delta:+.3f}")
    print(f"    Δ minority_recall   : {min_delta:+.3f}")
    if delta >= 0.05 and min_delta > 0:
        verdict = "PASS ✅  learning has a real edge → SWE-bench spend justified"
    elif delta > 0:
        verdict = "MARGINAL ⚠️  edge < 0.05 → corpus too weak; generate synthetic + re-run"
    else:
        verdict = "FAIL 🔴  learning does not beat static rubric on this data → reposition honestly"
    print(f"  VERDICT: {verdict}")
    print("━" * 70)

    out = {"n": n, "train": len(y_tr), "test": len(y_te), "k": args.k,
           "results": results, "delta_bal_acc": round(delta, 4),
           "delta_minority_recall": round(min_delta, 4), "verdict": verdict}
    (Path(__file__).parent / "experiment_e1.json").write_text(json.dumps(out, indent=2))
    print(f"saved → {Path(__file__).parent / 'experiment_e1.json'}")


if __name__ == "__main__":
    main()
