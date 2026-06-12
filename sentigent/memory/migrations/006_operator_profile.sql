-- 006_operator_profile.sql — the synthesized model of the operator (Phase 1, A2).
-- ProfileBuilder writes one versioned row here from CLAUDE.md (explicit) + the
-- decision_events signal (implicit), via a local LLM. This is the "model of you"
-- the autopilot will judge against. See docs/plans/2026-06-03-operator-autopilot-design.md (A2).

CREATE TABLE IF NOT EXISTS operator_profile (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id     TEXT NOT NULL,
    version      INTEGER NOT NULL,
    created_at   REAL NOT NULL,            -- unix epoch
    source       TEXT NOT NULL DEFAULT '', -- llm | explicit_only | manual
    model        TEXT NOT NULL DEFAULT '', -- which local model synthesized it
    profile_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_operator_profile_agent_version
    ON operator_profile (agent_id, version);
