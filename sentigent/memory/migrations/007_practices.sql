-- 007_practices.sql — your living "how I build" playbook (declared best practices).
-- Distinct from the LEARNED profile (decision_events → operator_profile): these are
-- practices you INTENTIONALLY adopt at the right milestone ("code review before a
-- milestone commit", "tests before pushing"). They (1) count toward Clone Readiness,
-- (2) the Operator judges your work against them, and (3) get adherence-tracked from
-- your real signal so you can see if you're actually holding to them.
-- See docs/plans/2026-06-03-operator-autopilot-design.md (Layer A — Profile).

CREATE TABLE IF NOT EXISTS practices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    text            TEXT NOT NULL,                       -- the practice, in your words
    domain          TEXT NOT NULL DEFAULT 'global',      -- testing | review | deploy | db | security | ...
    cadence         TEXT NOT NULL DEFAULT 'always',      -- always | commit | milestone | deploy | pr
    created_at      REAL NOT NULL,                       -- unix epoch
    active          INTEGER NOT NULL DEFAULT 1,
    times_followed  INTEGER NOT NULL DEFAULT 0,          -- adherence: held the practice
    times_skipped   INTEGER NOT NULL DEFAULT 0,          -- adherence: skipped it
    last_checked_at REAL
);

CREATE INDEX IF NOT EXISTS idx_practices_agent_active
    ON practices (agent_id, active);
