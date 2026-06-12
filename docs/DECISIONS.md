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
