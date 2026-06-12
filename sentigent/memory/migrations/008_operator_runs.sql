-- 008_operator_runs.sql — Fly-mode (Operator autopilot) persistence layer.
-- The durable record of every autonomous run: the plan it followed, the steps it
-- executed, the budget it burned, the full audit log of what it did, and every
-- moment it had to stop and ask the user (escalations). Local-first, fail-soft:
-- callers parse the JSON-encoded columns (done_criteria, payload, context).
-- See docs/plans/2026-06-03-operator-autopilot-design.md (§3 data model).

CREATE TABLE IF NOT EXISTS plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL,
    goal        TEXT NOT NULL,                  -- what the run is trying to achieve
    source      TEXT DEFAULT '',                -- where the goal came from (cli | hook | ...)
    created_at  REAL NOT NULL,                  -- unix epoch
    status      TEXT DEFAULT 'pending'          -- pending | active | done | abandoned
);

CREATE INDEX IF NOT EXISTS idx_plans_agent
    ON plans (agent_id);

CREATE TABLE IF NOT EXISTS plan_steps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL,
    idx             INTEGER NOT NULL,           -- ordinal within the plan
    description     TEXT NOT NULL,
    done_criteria   TEXT DEFAULT '{}',          -- JSON: how we know the step is complete
    status          TEXT DEFAULT 'pending',     -- pending | running | done | failed | skipped
    depends_on      TEXT DEFAULT '',            -- comma-separated step ids/idxs
    checkpoint_sha  TEXT DEFAULT ''             -- git sha captured when the step finished
);

CREATE INDEX IF NOT EXISTS idx_plan_steps_plan
    ON plan_steps (plan_id);

CREATE TABLE IF NOT EXISTS operator_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    plan_id         INTEGER,
    autonomy_level  TEXT DEFAULT 'assisted',    -- assisted | supervised | autonomous
    budget_usd      REAL DEFAULT 0,             -- ceiling for this run
    spent_usd       REAL DEFAULT 0,             -- accrued spend
    worktree        TEXT DEFAULT '',            -- isolated git worktree path
    status          TEXT DEFAULT 'running',     -- running | paused | done | aborted
    started_at      REAL NOT NULL,
    ended_at        REAL
);

CREATE INDEX IF NOT EXISTS idx_operator_runs_agent
    ON operator_runs (agent_id);

CREATE TABLE IF NOT EXISTS run_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL,
    step_id     INTEGER,
    ts          REAL NOT NULL,
    type        TEXT NOT NULL,                  -- step_start | tool_call | checkpoint | error | ...
    payload     TEXT DEFAULT '{}'               -- JSON event detail
);

CREATE INDEX IF NOT EXISTS idx_run_events_run
    ON run_events (run_id);

CREATE TABLE IF NOT EXISTS escalations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL,
    step_id         INTEGER,
    ts              REAL NOT NULL,
    question        TEXT NOT NULL,              -- what the operator needs answered
    context         TEXT DEFAULT '{}',          -- JSON context around the question
    risk            REAL DEFAULT 0,             -- 0..1 risk score of proceeding
    status          TEXT DEFAULT 'open',        -- open | answered
    user_decision   TEXT DEFAULT '',            -- the user's answer
    answered_at     REAL
);

CREATE INDEX IF NOT EXISTS idx_escalations_run
    ON escalations (run_id, status);
