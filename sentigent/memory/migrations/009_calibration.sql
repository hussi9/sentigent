-- 009_calibration.sql — ConfidenceCalibrator signal (G3) + the learning loop's
-- feedback ledger. Append-only: one row per judged decision whose outcome the user
-- later confirmed (approved/reverted/edited). Aggregated on read into per-domain
-- "when the clone was confident, was it right?" — which graduates autonomy.
-- See docs/plans/2026-06-03-operator-autopilot-design.md (G2/G3).

CREATE TABLE IF NOT EXISTS calibration_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL,
    domain      TEXT NOT NULL DEFAULT 'global',
    predicted   TEXT NOT NULL DEFAULT '',   -- the gate's decision (continue|correct|escalate)
    confidence  REAL NOT NULL DEFAULT 0.0,  -- the gate's confidence at the time
    was_correct INTEGER NOT NULL DEFAULT 0, -- did the user agree / not revert?
    ts          REAL NOT NULL,
    source      TEXT NOT NULL DEFAULT ''    -- escalation_answer | revert | edit | manual
);

CREATE INDEX IF NOT EXISTS idx_calibration_agent_domain
    ON calibration_events (agent_id, domain);
