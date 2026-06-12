-- 005_decision_events.sql — the REAL user-preference signal (Phase 0, A1/DecisionCapture).
-- Replaces the fiction that "a tool ran without error" means anything. These rows
-- record moments the human actually expressed judgment: approving, rejecting,
-- correcting, or reverting work. This is the fuel for the operator profile.
-- See docs/plans/2026-06-03-operator-autopilot-design.md (A1).

CREATE TABLE IF NOT EXISTS decision_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id      TEXT NOT NULL,
    org_id        TEXT NOT NULL DEFAULT 'default',
    ts            REAL NOT NULL,                 -- unix epoch
    kind          TEXT NOT NULL,                 -- approve | reject | correct | revert
    domain        TEXT NOT NULL DEFAULT 'global',
    signal        TEXT NOT NULL DEFAULT '',      -- what the user did (verbatim-ish, trimmed)
    target        TEXT NOT NULL DEFAULT '',      -- what it was about (tool/file/command)
    prior_trace_id TEXT NOT NULL DEFAULT '',     -- the decision being reacted to, if known
    source        TEXT NOT NULL DEFAULT '',      -- prompt_reaction | bash_revert | ...
    confidence    REAL NOT NULL DEFAULT 1.0,     -- how sure we are this is a real signal
    meta          TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_decision_events_agent_ts
    ON decision_events (agent_id, ts);
CREATE INDEX IF NOT EXISTS idx_decision_events_kind
    ON decision_events (kind);
