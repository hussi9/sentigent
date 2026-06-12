-- Cost telemetry: per-tool-call model × token usage and savings vs opus baseline.
CREATE TABLE IF NOT EXISTS cost_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id        TEXT,
    agent_id        TEXT,
    model           TEXT,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    tool_name       TEXT,
    cost_usd        REAL    NOT NULL DEFAULT 0.0,
    baseline_cost_usd REAL  NOT NULL DEFAULT 0.0,
    savings_usd     REAL    NOT NULL DEFAULT 0.0,
    meta            TEXT,                         -- JSON
    ts              REAL    NOT NULL DEFAULT (unixepoch('now')),
    year            INTEGER GENERATED ALWAYS AS (CAST(strftime('%Y', ts, 'unixepoch') AS INTEGER)) VIRTUAL,
    month           INTEGER GENERATED ALWAYS AS (CAST(strftime('%m', ts, 'unixepoch') AS INTEGER)) VIRTUAL
);

CREATE INDEX IF NOT EXISTS idx_cost_events_agent  ON cost_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_cost_events_ts     ON cost_events(ts);
CREATE INDEX IF NOT EXISTS idx_cost_events_model  ON cost_events(model);
