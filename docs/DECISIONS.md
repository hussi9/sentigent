# Decision Log

ADR-lite. One entry per significant design decision. Newest first. Each records the **context**
(why it came up), the **decision**, its **status**, and the **rationale/consequences**. Research
backing many of these lives in `docs/DESIGN-RESEARCH.md`.

Status legend: `accepted` (decided, may not be built yet) · `shipped` (in the codebase) ·
`deferred` (parked, conditions noted) · `superseded` (replaced — link the replacement).

---

## D-009 — Add a design-research doc + this decision log
- **Date:** 2026-06-12 · **Status:** shipped
- **Context:** Roadmap calls were being made from research (frontier-team + agent-builder blogs)
  with no durable record. New contributors (human or agent) couldn't see the "why."
- **Decision:** Keep `docs/DESIGN-RESEARCH.md` (living research synthesis) and `docs/DECISIONS.md`
  (this log). Append, don't rewrite.
- **Rationale:** Matches the "agent-first / repo-legible" practice — the reasoning is part of the
  repo, not lost in chat. Cheap, compounding.

## D-008 — No invented or modeled metrics in public claims
- **Date:** 2026-06-12 · **Status:** accepted (policy)
- **Context:** A "$2,245 → $449, 80% cost saved" figure was about to be published. On inspection
  the `baseline_cost_usd` was a hardcoded 5× multiplier over *estimated* tokens — a modeled
  counterfactual, not a measurement.
- **Decision:** Never publish modeled/illustrative numbers as if measured. Cost or savings claims
  require a real instrumented A/B with actual token counts.
- **Rationale:** A skeptical engineer pulling the schema would tear it apart; one weak number
  discredits the honest ones. Trust is the product. Mechanism claims (routing/avoided loops cost
  less) are fine because they're arithmetic, not measurement.

## D-007 — Frontier-formula receipt
- **Date:** 2026-06-12 · **Status:** accepted (queued)
- **Context:** AWS/OpenAI frame agent value as a product of three factors. Sentigent's autonomy
  receipt already measures the inputs.
- **Decision:** Reframe the receipt to report the three multiplicative factors (AI handles
  low-judgment work × uninterrupted high-judgment focus × instant expertise).
- **Rationale:** Sentigent becomes the *measurement instrument* for the metric these teams cite —
  honest, since it reads the brain. Cheap (reframing, not new plumbing). After D-006.

## D-006 — Shift-left verification gate (next build)
- **Date:** 2026-06-12 · **Status:** accepted (next)
- **Context:** Anthropic names "verify end-to-end before done, then self-correct" as the mechanism
  agents fail without; OpenAI enforces it via CI; AWS calls it shift-left testing. Sentigent has a
  `verifier` + self-repair but doesn't gate "done" on a real test run.
- **Decision:** Extend `verifier.py` + self-repair so a step's Definition-of-Done requires a green
  run of the project's own test command, with bounded self-correction on failure — never
  auto-clearing the hard-rule wall.
- **Rationale:** Triple-endorsed by the field; extends existing code; makes autonomy *trustworthy*,
  which is the gap reviewers probe. See `DESIGN-RESEARCH.md`.

## D-005 — Learned Steering File (`AGENTS.md`)
- **Date:** 2026-06-12 · **Status:** shipped
- **Context:** Frontier teams rely on steering files but hand-write them and they rot. Sentigent
  already holds the same info as behavior.
- **Decision:** Generate a standard `AGENTS.md` from the brain — hard rules, conventions, practices,
  preferences, when-to-ask, risk posture, learned decision defaults, calibrated autonomy, drift
  line. `sentigent/operator/steering_doc.py` + `scripts/export_steering.py` + tests.
- **Rationale:** Wedge = *learned, not hand-written; knows when it's stale.* Composes over
  `judgment_doc.py`; pure read-over-store; deterministic; no new deps.
- **Consequences:** Surfaced + fixed a latent profile-load bug → D-004.

## D-004 — Fix profile load (`get_latest_operator_profile`)
- **Date:** 2026-06-12 · **Status:** shipped
- **Context:** `export_judgment.py` (and the new `export_steering.py`) loaded the operator profile
  via a nonexistent `get_operator_profile()`, silently caught → empty profile. This is why
  `JUDGMENT.md` only ever rendered hard rules.
- **Decision:** Use `store.get_latest_operator_profile()` + `json.loads(profile_json)` in both
  scripts.
- **Rationale:** Restores conventions/risk-posture/preferences to both exported docs.

## D-003 — Layer 2 (team/org sync) is a demand-gated roadmap, not built
- **Date:** 2026-06-12 · **Status:** deferred (demand-gated)
- **Context:** The team/org sync layer was being overstated as "built but dormant." The
  service-role key is stale; nothing real ships there.
- **Decision:** Frame Layer 2 as roadmap only — built on adoption/requests (open an issue), not
  before. Layer 1 (local, solo) is the real product.
- **Rationale:** Honesty + a demand-signal funnel. `org_relationships` is the stub lane.

## D-002 — Single root agent + Clone Resolver, not multi-agent
- **Date:** 2026-06-09 (validated 2026-06-12) · **Status:** accepted (standing)
- **Context:** Tempting to spawn sub-agents for parallelism.
- **Decision:** Stay single-root: the operator loop delegates isolated steps; the CloneResolver
  answers blockers as the user. No free-form agent swarm.
- **Rationale:** Independently validated by Cognition ("Don't build multi-agents") — dispersed
  decisions + conflicting assumptions make swarms fragile; missing context is the root cause.

## D-001 — Local-first judgment (Ollama + SQLite), inviolable hard-rule wall
- **Date:** founding · **Status:** accepted (standing)
- **Context:** A model of your judgment is the most personal data there is; the riskiest ops must
  never be probabilistically "cleared."
- **Decision:** Gate/resolver run on a local model; the brain is a local SQLite DB; the hard-rule
  wall (force-push, prod-DB, secrets, rm -rf, unprompted external send) is the first branch in
  escalation and is never auto-cleared. Fail-soft → `needs_human` at confidence 0.
- **Rationale:** Privacy, cost, and trust. Matches the field's "durable external memory" + "humans
  steer" conclusions while keeping data on the user's machine.

## D-010 — Verify capability by execution, not by function-existence (code-review finding)
- **Date:** 2026-06-12 · **Status:** accepted (policy) + corrective work in progress
- **Context:** A "where Sentigent sits" table marked the learning loop ✅. A line-by-line review +
  live execution showed the running MCP server is **stale** (answering an escalation wrote 0
  precedents), and the live brain had **0 precedents / 0 calibration events from 11 real answers** —
  the compounding loop had never closed. The on-disk code is correct (forced precedent id=1).
- **Decision:** (1) Treat "exists in code" as unproven until executed against the live store.
  (2) Corrective P0 ahead of new features: reload the MCP server, backfill precedents from the
  already-answered escalations, and make outcomes flow into calibration.
- **Rationale:** The project's whole pitch is *compounding learned judgment*. A loop that never
  closes is the difference between a real product and a demo. Found because we code-reviewed
  instead of feature-list-reviewed.

## D-011 — Calibration loop is wired; proven by test (not rebuilt)
- **Date:** 2026-06-12 · **Status:** shipped (test) — capability already present
- **Context:** Roadmap said "build calibration-from-outcomes." Code review showed `operate.py:532-536`
  already stashes `clone_attempt` into the escalation context, and `learn_from_escalation_answer`
  already calibrates it. Live calibration was empty only because every real escalation so far was
  a hard rule (resolver skipped) or verify-failed (resolver not run) — unexercised, not missing.
- **Decision:** Don't rebuild. Add `tests/test_calibration_loop.py` proving the path fires when a
  clone attempt is present, and proving it correctly does NOT calibrate without one.
- **Rationale:** Honest accounting (D-010): prove by execution. The test is the regression guard.

## D-012 — Shift-left test gate: populate the test_cmd the Verifier already runs
- **Date:** 2026-06-12 · **Status:** shipped
- **Context:** `verifier.py:161` already runs a `test_cmd` done-criterion (the shift-left gate). The
  gap was *supplying* it without the planner hand-writing the command.
- **Decision:** Add `sentigent/operator/shiftleft.py` — `detect_test_command(cwd)` (Node/Python/
  Rust/Go, read-only) + `ensure_test_criterion()` to fold it into a step's done-criteria. Tests
  include a real proof that a failing `test_cmd` blocks "done".
- **Rationale:** Triple-endorsed practice; additive; no hot-path rewrite. Wiring it into operate's
  DoD by default is a follow-on (touches the unproven execute path — deferred deliberately).

## D-013 — Brain doctor: make silent loop failures loud
- **Date:** 2026-06-12 · **Status:** shipped
- **Context:** The learn-loop gap (D-010) was invisible — nothing surfaced "answers recorded, 0
  precedents." A judgment product that can't see its own broken loop is the worst failure mode.
- **Decision:** Add `sentigent/operator/doctor.py` (`health_report`) + `scripts/doctor.py`:
  vital signs + two named symptoms (stale learn-loop; precedents-without-calibration) with the fix
  inline. Exit 1 on warnings so it can gate CI/cron.
- **Rationale:** Observability for the loops the product's value depends on. Cheap, high-leverage.

## D-014 — Close the open gaps honestly (self-heal learning; calibration self-fills; execute = a real flight)
- **Date:** 2026-06-12 · **Status:** (1) shipped · (2) accepted-as-is · (3) honest-deferred
- **Context:** Three gaps were open: (1) a stale MCP server records answers but skips the learn
  write-back; (2) calibration is empty; (3) the execute-mode verify path is unproven live.
- **Decision:**
  1. **FIXED.** `operate()` now reconciles answered-but-unlearned escalations at every run start
     (`backfill_precedents`), and `scripts/doctor.py --fix` does it on demand. Learning is now
     robust to a stale server — the next flight always closes the gap.
  2. **No build.** Calibration accrues only from real resolver-attempted escalations a human then
     answers. Auto-scoring the clone's own resolutions as "correct" would be the clone grading
     itself — banned (D-008). The doctor surfaces the empty state; it fills from real runs.
  3. **Honest-deferred.** The Verifier + `test_cmd` gate is proven by unit test
     (`test_shiftleft.py`). The only remaining proof is `operate()`'s execute path on a real
     flight, which spawns a nested worker drawing real quota. Deferred to a real run — not faked
     with a brittle box-check test.
- **Rationale:** fix what genuinely fixes; never fake a green check. That's the whole point of
  this code-review pass.

## D-015 — Flight summary panel (fix fly-mode UIUX)
- **Date:** 2026-06-12 · **Status:** shipped
- **Context:** Fly mode ended in event-JSON spam — no sense of achievement or usefulness.
- **Decision:** `sentigent/operator/flight_summary.py` (`cumulative_stats` + `session_stats` +
  `render_panel`) + `scripts/flight_summary.py`: one clean, rewarding panel read live from the
  brain — this-flight + all-time + a decision-DNA bar. Real numbers only (D-008).
- **Rationale:** the payoff of autonomy should be felt, not buried in logs.

## D-016 — Backfill dedup keys on (blocker, decision), not blocker alone
- **Date:** 2026-06-12 · **Status:** shipped
- **Context:** A self-review of the backfill module (D-014's self-heal path) found its idempotency
  keyed on blocker text alone. The same blocker answered two different ways — "build demo?" →
  approve once, skip another time — collapsed into ONE precedent; the second answer was silently
  dropped. Invisible on the live brain (a no-dedup manual backfill ran first) but a fresh user, and
  the run-start reconcile in `operate()`, both lose the second decision. Reproduced: 2 answered →
  1 precedent.
- **Decision:** dedup on `(blocker, decision)`. Same blocker + same decision is a real duplicate;
  same blocker + different decision is a distinct precedent. `_norm_decision` mirrors the store's
  vocabulary map EXACTLY (kept in lockstep with `store.learn_from_escalation_answer`) so the key
  matches the stored precedent and re-runs stay idempotent. Regression test added.
- **Rationale:** the clone should remember that a blocker can resolve more than one way — that
  spread IS the judgment. Collapsing it is lossy, and dropping data silently is the opposite of
  this code-review pass's whole point.

## D-017 — Sweep continued: precise shift-left detection + partial-staleness doctor signal
- **Date:** 2026-06-12 · **Status:** shipped
- **Context:** Continuing the self-review. Two more real (latent) defects:
  (a) `shiftleft.detect_test_command` returned `pytest -q` for *any* `pyproject.toml`/`setup.cfg`
  — files that frequently exist only for black/ruff config with zero tests. Once wired into the
  Verifier gate that would fail a genuinely-done step on a phantom test runner. (Not yet wired, so
  caught before it could bite.) (b) `doctor`'s `learn_loop_ok` was binary (`answered>0 and
  precedents==0`) and so blind to *partial* staleness — some answers learned, some not.
- **Decision:**
  (a) Require a real pytest signal: a `tests/` dir, a `pytest.ini`, or an explicit `pytest` mention
  in `tox.ini`/`pyproject.toml`/`setup.cfg` (content check, read-only). Bare config files no longer
  gate. (b) Compute the learn-loop signal from a **dry-run backfill** — it counts answered
  escalations whose `(blocker, decision)` isn't yet a precedent, reusing D-016's exact dedup. This
  catches partial staleness AND never false-alarms on legitimate dedup. Regression tests for both.
- **Rationale:** a false test-gate and a blind health check are both silent failures — the precise
  thing this sweep exists to kill. Reuse the canonical dedup rather than inventing a second notion
  of "learned" that could drift from it.

## D-018 — Verifier: close three vacuous-pass holes in the anti-hallucination gate
- **Date:** 2026-06-12 · **Status:** shipped
- **Context:** Highest-severity finding of the sweep — in the Verifier itself, the gate whose whole
  job is "never falsely pass." An empty/whitespace `test_cmd` or `build_cmd` runs `bash -c ""` →
  exit 0 → a vacuous PASS. An empty `files_exist: []` reports "all 0 paths exist" → PASS. Any of
  these as a step's only criterion marks it **done with zero real verification** — so in execute
  mode self-repair never fires and a half-done step ships. Reproduced all three.
- **Decision:** conservative guards at the choke points. `_run_cmd`: a blank command can verify
  nothing → FAIL. `_check_files_exist`: an empty list verified nothing → FAIL. Aligns the code with
  its own stated contract ("done requires at least one real check that actually ran"). Three
  regression tests added.
- **Rationale:** the verifier is the load-bearing wall of the whole loop's honesty. A false green
  here defeats every downstream guarantee — it must fail closed, not open.

## D-019 — Execute-mode verifier proven live (closes gap-3) + core-loop sweep clean
- **Date:** 2026-06-13 · **Status:** shipped
- **Context:** The last open gap (D-014 #3): the Verifier + `test_cmd` gate firing inside
  `operate(execute=True)` was only unit-proven, never exercised end-to-end. Also completed the
  code-review sweep of the remaining core-loop modules: `gate.py`, `resolver.py`, `escalation.py`.
- **Decision:**
  1. **Gap-3 closed.** New `tests/test_operate_execute.py` drives the real `operate()` loop in
     execute mode against a real MemoryStore, a real temp git worktree, and real subprocess
     `test_cmd` criteria run by the real Verifier — only the LLM worker + clone are injected (a test
     must not burn Anthropic quota, and that's not what this gap is about). Proves both arms live:
     passing test_cmd → `verified=True` + real git checkpoint; failing test_cmd → self-repair
     retries exactly `max_attempts`, `verified=False`, run pauses, `verify_failed` escalation filed.
  2. **Core-loop sweep clean.** `gate`/`resolver`/`escalation` reviewed; no reproducible defects —
     the session's bugs all lived in the learning/verification plumbing, not the decision core.
- **Open (tuning, not a defect):** under `TRUSTED` autonomy with the LLM offline, the gate's
  heuristic-fallback confidence (0.25) exactly meets the TRUSTED floor (0.25), so an unjudged step
  can auto-proceed. Flagged for Hussain as a risk-posture choice rather than silently changed.
- **Rationale:** "unproven" was the honest status for months; the honest closure is a permanent
  end-to-end regression test, not a one-off manual flight that proves nothing tomorrow.

## D-020 — Fly-mode safety-floor sweep: PolicyWall stickiness + first risk tests
- **Date:** 2026-06-13 · **Status:** shipped
- **Context:** Swept fly mode's safety-critical surface — `risk.py` (PolicyWall hard rules),
  `safety.py` (KillSwitch + BudgetGovernor), and confirmed the killswitch is actually polled
  (operate.py:387, per-run + global, before every step). `safety.py` is clean and the killswitch
  is live. But `RiskAssessor.assess()` carried `policy_wall` on whichever rule won the *score*,
  and the safety floor had **zero test coverage**.
- **Decision:**
  1. **PolicyWall is now sticky.** If ANY hard rule matches, the verdict carries `policy_wall=True`
     regardless of which rule wins the score. The old code was safe only by the numeric coincidence
     that no non-wall base exceeded any wall base — one future rule edit (e.g. a 0.9 non-wall
     "deploy-to-prod") would have silently dropped a co-occurring hard-rule escalation. Now it fails
     closed. Behavior on the current ruleset is unchanged.
  2. **First `tests/test_risk.py`.** Locks the hard rules, the low-risk routine cases, and the
     stickiness invariant (proven via a patched future high-base non-wall rule).
- **Open (tuning, not a defect):** the `TRUSTED`-offline gate floor from D-019 still stands as a
  risk-posture choice for Hussain.
- **Rationale:** the hard-rule wall is the one guarantee that must hold even when everything else
  (profile, gate, clone) is wrong. A guarantee with no tests and a numeric-coincidence dependency
  isn't a guarantee — make it provable and fail-closed.

## D-021 — Chain circuit-breaker + borderline-decision trail (Reddit launch feedback)
- **Date:** 2026-06-13 · **Status:** shipped
- **Context:** r/LLMDevs launch feedback (u/Ill_Formal7579): "the 83% agreement gives me pause — that
  17% is where the damage lives; how do you surface those disagreements before they compound into a
  chain of bad decisions?" Existing guards (calibrated floors, policy wall, verifier) handle the
  single bad call; nothing addressed a *chain* of barely-confident auto-applies drifting silently.
- **Decision:** new `chain_guard.py` — `is_borderline` (cleared the floor but only just:
  floor ≤ conf < floor+margin) + `ChainGuard` (tracks consecutive borderline auto-applies; a
  confident call resets the streak). Wired into `operate()`'s resolver path: every borderline
  auto-apply is recorded to a reviewable trail (`RunResult.borderline` + `borderline_autoapply`
  events); after `chain_break_after` (default 3) in a row the breaker TRIPS — the run does NOT
  auto-apply, it pauses for a human checkpoint (`chain_breaker` event). Defaults
  `chain_break_after=3`, `chain_margin=0.10`, both tunable.
- **Bug caught in build:** the first wiring left `esc = _no_ask(esc)` outside the non-trip branch,
  so a tripped step auto-applied anyway — the exact failure the feature prevents. Fixed: all
  auto-apply logic now lives strictly inside the non-trip `else`. Regression test asserts the run
  pauses after 3 and only 2 steps completed.
- **Rationale:** the honest answer to "how do you catch the 17%" is: make the borderline calls
  visible, and refuse to let a streak of them run unattended. Surfacing + a circuit-breaker beats
  pretending the agreement rate is 100%.
