-- 010_precedents.sql — the Clone Resolver's memory of "what would Hussain do here?"
-- Append-only ledger of resolved blockers: every human escalation-answer AND every
-- seeded precedent lands here, keyed by category, so the resolver can retrieve a
-- prior decision next time a similar blocker appears. This is the substrate that
-- makes autonomy COMPOUND — answered once, auto-resolved thereafter.
-- See docs/superpowers/specs/2026-06-09-sentigent-loop-design.md (§3 Clone Resolver).

CREATE TABLE IF NOT EXISTS operator_precedents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   TEXT NOT NULL,
    category   TEXT NOT NULL DEFAULT 'general', -- risk/trigger class the precedent applies to
    blocker    TEXT NOT NULL,                   -- the step/question text that was blocked
    decision   TEXT NOT NULL,                   -- approve | skip | takeover
    rationale  TEXT NOT NULL DEFAULT '',        -- in the user's voice (why)
    source     TEXT NOT NULL DEFAULT '',        -- human_answer | seed
    ts         REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_precedents_agent_category
    ON operator_precedents (agent_id, category);
