# Sentigent — Architecture & Roadmap

> Status: model is canonical; build status is labelled per layer. Nothing is claimed
> as done unless marked **live**. This frames Sentigent around the three layers of
> context that govern every decision the loop makes.

## The model — three layers of context

Every call the loop makes at a blocker is the product of three context layers. They
do not overlap — each has a distinct **owner**, **lifespan**, and **question it answers**:

```
   ┌────────────────────────────────────────────────────────────────────────┐
   │  ORG · Policy        "What is everyone ALLOWED to do?"      [building]   │
   │  Hard rules it can never auto-clear (force-push · prod-DB · secrets) +   │
   │  a governed catalog of approved skills · MCP servers · tools.           │
   │  Owner: org admins   ·   Scope: all people + all projects               │
   └───────────────────────────────▲────────────────────────────────────────┘
                                    │ bounds
   ┌───────────────────────────────┴────────────────────────────────────────┐
   │  PROJECT · Plan      "What does THIS work require?"             [live]   │
   │  Goal · phased plan · per-step done-criteria · repo conventions +        │
   │  guardrails.   Owner: the repo   ·   Scope: everyone on this codebase    │
   └───────────────────────────────▲────────────────────────────────────────┘
                                    │ scopes
   ┌───────────────────────────────┴────────────────────────────────────────┐
   │  INDIVIDUAL · Profile  "What would YOU do?"                     [live]   │
   │  Your standards · preferences · push-vs-ask judgment (model-of-you).     │
   │  Owner: you   ·   Scope: travels with you across every project · local   │
   └────────────────────────────────────────────────────────────────────────┘
```

**The decision rule — the whole product in one line:**

> **decide = Profile · Plan · Policy** — at every blocker the clone answers
> *what **I'd** do, given **this plan**, within **the org's rules***. That is exactly
> why the loop can keep going without paging you: it already holds the three pieces of
> context you would otherwise have to supply by hand.

---

## Layer 1 — Individual · Profile — *live*

The model-of-you. Your declared standards, preferences, and the push-vs-ask judgment
that decides blockers in your voice, with a confidence calibrated from how you've
actually decided before.

- **Where:** local SQLite brain, <50ms, nothing leaves your machine.
- **Lifespan:** persists across every project you touch — it's *yours*, not a repo's.
- **Built:** `operator/resolver.py` (CloneResolver) + profile + calibration. Proven.
- **Next:** sharper thresholds from real usage; warm-model daemon for cold-start.

## Layer 2 — Project · Plan — *live*

What *this* work requires: the goal, the phased plan, per-step done-criteria, and the
repo's own conventions and guardrails. Shared by everyone working in the codebase.

- **Where:** durable loop state on disk (`~/.sentigent/loops/`) + per-repo guardrail packs.
- **Lifespan:** lives with the codebase; survives the end of any session.
- **Built:** `operator/loop_driver.py` (plan, per-step gate, verify, resume, FAP) +
  `guardrails/*.yaml`. Proven.
- **Next:** richer plan authoring; project-level done-criteria templates.

## Layer 3 — Org · Policy — *building*

The rules that bind every agent and project, and the catalog of what they may use.

- **Faculties:** hard rules it can never auto-clear (force-push, prod-DB, secrets,
  external sends) + the **capability registry** (approved skills / MCP servers / tools,
  permission-scoped and discoverable by "most-used") + budgets + trace + approval gates.
- **Owner:** org admins. **Scope:** across all people and all projects.
- **Today:** scattered primitives (BudgetGovernor, policy_engine, guardrails, killswitch,
  escalations, `sentigent_route`) — **no unified policy layer, no registry, no UI**.
- **Next:** this is the build. See sequence below.

---

## Runtime note (where it executes)

The three layers are *context*, not boxes. At runtime they resolve in two places:
- **On your machine** — the loop + clone + Profile + the active Plan run locally.
- **The org control panel** — Policy is authored, the registry is curated, and every
  run is traced/governed. (This is the Layer-3 build.)

Local-first is the default; sharing context upward (team Plan, org Policy) is opt-in.

## Build sequence — Org · Policy (none started)
- **R1 — Trace spine.** One canonical trace per run (goal→stop): which Profile/Plan/Policy
  context applied, capabilities used, checks, approvals, stop reason. *No trace = no governance.*
- **R2 — Capability registry.** skills / MCP / tools tables: entry + approval + permission
  scope + version + usage counter (→ "most-used in org"). RLS org-scoped.
- **R3 — In-loop resolution.** The loop asks "what may I use?" → gets the org's approved+scoped
  set; logs each use (feeds the most-used ranking).
- **R4 — Enforcement.** budgets / hard-rules / approval gates consulted before acting; honor
  stop/kill from the panel.
- **R5 — Control panel UI** on sentigent.xyz: registry (browse/approve/scope), budgets,
  approvals inbox, trace explorer.
- **R6 — Proof per faculty.** each ships with a reproducible artifact (a real blocked tool,
  a real budget stop, a real approved gate, a real trace) — never a claim without one.

## Cross-cutting builds (validated by the frontier-team writeups)

The AWS "frontier team" pieces (ProServe / Kiro) independently describe the same practices
Sentigent is built on — steering files, spec/done-criteria, human-gates-where-judgment-matters,
compounding from encoded expertise. Two capabilities they have that Sentigent does **not** yet,
now explicit on the roadmap:

- **X1 — Parallel / async runs.** Today the loop is a single chain. Frontier teams "maintain a
  backlog of well-scoped tasks, run multiple agents in parallel, review async." Build: drive N
  independent loops from a task list with one combined FAP receipt. (Foundation: each loop is
  already durable + isolated by `loop_id`.)
- **X2 — Org knowledge base.** Their agents carry "a knowledge base of learnings from thousands
  of engagements." This is the Org-layer shared-patterns build (sits on R2's registry + the
  cross-org pattern pool) — opt-in, anonymized, never default. Pairs with the auto-written
  **steering file** (`export_steering.py` → `AGENTS.md`): Sentigent *generates* steering files
  from real behaviour rather than making people hand-maintain them — the wedge vs. hand-built
  frontier-team context.
- **X3 — ARD interop (Google Cloud Agentic Resource Discovery).** ARD is the emerging open
  standard for agents to **discover** capabilities across the web and **verify** the publisher's
  identity (a domain hosts a signed `/.well-known/ai-catalog.json`; registries index catalogs;
  agents connect via MCP / A2A / API). It is *discovery + trust* — the layer **below** Sentigent's
  *governance + judgment*. The fit: **ARD finds & verifies a capability → Org · Policy decides if
  it's approved + in budget → the clone decides act-vs-ask.** Three moves, cheapest first:
  - **(a) Publish** Sentigent as an ARD catalog — `/.well-known/ai-catalog.json` on the project
    domain describing our MCP capabilities (`operator_*`, `loop_*`, `clone_*`, `sentigent_evaluate`),
    domain = cryptographic identity. Same "publish from real behaviour" move as the steering file;
    makes Sentigent discoverable + verifiable in the agent web. *(Draft authored: `docs/ard/`.)*
  - **(b) Consume** ARD as the discovery backend for the Org · Policy capability registry (R2) —
    adopt the open catalog format instead of inventing a silo; Policy adds approved/budgeted on top.
  - **(c) Verify-gate** — an external capability that is not ARD-verified → escalate. Verified
    provenance "earns autonomy," consistent with the steering-file/autonomy framing.

  Guardrail: consume the **open spec** and self-host the catalog — never require Google's managed
  *Agent Registry* / Gemini Enterprise. Stays local-first/OSS. ARD is brand-new, so lock in the
  cheap reversible moves (a, c) and let the spec stabilize before the deep registry build (b).
- **R-CLD — Closed-loop delivery discipline.** The engine (`loop_driver.py`) is a closed loop
  already; this adds *delivery* discipline on top (skill: `skills/closed-loop-delivery/SKILL.md`).
  Three gaps — **all shipped 2026-06-17** (TDD, 43 focused tests green): **(1) output-contract
  render** ✅ `loop_driver.contract(id)` + `sentigent loop contract <id>` prints the per-criterion
  DoD checklist (✅/❌/○ + verify cmd + status) from existing state, reusing `metrics()` for FAP;
  **(2) PR review loop** ✅ `operator/review_loop.py` — `fetch_pr_feedback` (gh, fail-soft) +
  `classify` (valid vs non-actionable) + `to_steps` + `poll_windows` (3m/6m/10m, injectable sleep);
  **(3) deploy-then-runtime-verify** ✅ `operator/runtime_verify.py` — `run_check` (captures
  evidence, fail-soft) + `http_check`/`log_check` (build a runtime-evidence command for a step's
  `--verify`). Next: wire (2)/(3) into the driver's drive loop so review items auto-inject as steps.

## Honesty line
Individual (Profile) and Project (Plan) are **live and proven**. Org (Policy) is **scattered
primitives** today; this roadmap builds it around the capability registry. Public status stays
`building` until each faculty has its reproducible artifact.
