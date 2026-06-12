-- Routing seed data imported from skill_router_log.jsonl
-- Kept separate from live episodes until validated by real outcomes.
CREATE TABLE IF NOT EXISTS routing_seeds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_hash  TEXT    NOT NULL,
    prompt_text  TEXT,
    task_type    TEXT,              -- debug | build | operate | research | unknown
    skill        TEXT,
    agent        TEXT,
    model        TEXT,
    confidence   REAL,
    avg_sim      REAL,
    margin       REAL,
    neighbors    TEXT,              -- JSON array of {prompt, skill, sim}
    embedding    TEXT,              -- JSON array of floats (384-dim)
    outcome      TEXT    DEFAULT 'neutral',  -- neutral | correct | incorrect
    source       TEXT    DEFAULT 'skill_router_import',
    imported_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_routing_seeds_task_type ON routing_seeds(task_type);
CREATE INDEX IF NOT EXISTS idx_routing_seeds_skill     ON routing_seeds(skill);
CREATE INDEX IF NOT EXISTS idx_routing_seeds_outcome   ON routing_seeds(outcome);
CREATE UNIQUE INDEX IF NOT EXISTS idx_routing_seeds_hash ON routing_seeds(prompt_hash);
