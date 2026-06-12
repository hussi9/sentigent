-- Phase 2: Task Context Layer
-- Adds org_tasks table for tracking declared tasks and their outcomes.
-- This is the foundational Layer 2 table for task-anchored judgment.

-- ── org_tasks ─────────────────────────────────────────────────────────────────
-- One row per declared task. Agents write here via sentigent_start_task().
-- Scope violations, episode counts, and outcomes feed org-level learning.

CREATE TABLE IF NOT EXISTS org_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    task_id         TEXT NOT NULL,          -- matches Layer 1 active_tasks.task_id
    goal            TEXT NOT NULL,
    scope           TEXT[] DEFAULT '{}',    -- declared file/service scope
    authorized_by   TEXT NOT NULL DEFAULT 'user',  -- 'user' | 'policy' | 'org_admin'
    success_criteria TEXT[] DEFAULT '{}',
    constraints     TEXT[] DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'in_progress'
                        CHECK (status IN ('in_progress', 'complete', 'abandoned')),
    outcome         TEXT CHECK (outcome IN ('correct', 'incorrect', NULL)),
    summary         TEXT,
    episode_count   INTEGER NOT NULL DEFAULT 0,
    scope_violations INTEGER NOT NULL DEFAULT 0,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (org_id, task_id)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_org_tasks_org_id
    ON org_tasks (org_id);

CREATE INDEX IF NOT EXISTS idx_org_tasks_agent_id
    ON org_tasks (agent_id);

CREATE INDEX IF NOT EXISTS idx_org_tasks_status
    ON org_tasks (org_id, status);

CREATE INDEX IF NOT EXISTS idx_org_tasks_started_at
    ON org_tasks (org_id, started_at DESC);

-- ── Row Level Security ────────────────────────────────────────────────────────

ALTER TABLE org_tasks ENABLE ROW LEVEL SECURITY;

-- Members can read tasks for their org
CREATE POLICY "org_tasks_select_policy" ON org_tasks
    FOR SELECT
    USING (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid()
        )
    );

-- Agents write via service role key (server-side only)
CREATE POLICY "org_tasks_insert_policy" ON org_tasks
    FOR INSERT
    WITH CHECK (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "org_tasks_update_policy" ON org_tasks
    FOR UPDATE
    USING (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid()
        )
    );

-- ── episode_chains ────────────────────────────────────────────────────────────
-- Links ordered episodes to their parent task.
-- Enables semantic lifting: episode chain → task → project → initiative.

CREATE TABLE IF NOT EXISTS episode_chains (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          TEXT NOT NULL,
    task_id         TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    trace_ids       TEXT[] NOT NULL DEFAULT '{}',   -- ordered list of trace_ids
    outcome         TEXT CHECK (outcome IN ('correct', 'incorrect', 'neutral', NULL)),
    duration_seconds INTEGER,
    scope_violations INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_episode_chains_org_task
    ON episode_chains (org_id, task_id);

ALTER TABLE episode_chains ENABLE ROW LEVEL SECURITY;

CREATE POLICY "episode_chains_select_policy" ON episode_chains
    FOR SELECT
    USING (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid()
        )
    );

-- ── task_id column on synced_episodes ────────────────────────────────────────
-- Links individual episodes to their parent task for chain assembly.

ALTER TABLE synced_episodes
    ADD COLUMN IF NOT EXISTS task_id TEXT;

CREATE INDEX IF NOT EXISTS idx_synced_episodes_task_id
    ON synced_episodes (task_id)
    WHERE task_id IS NOT NULL;

-- ── Comments ─────────────────────────────────────────────────────────────────

COMMENT ON TABLE org_tasks IS
    'Phase 2: Task Context Layer. One row per declared agent task. '
    'Scope violations and episode counts feed org-wide judgment learning.';

COMMENT ON TABLE episode_chains IS
    'Phase 5: Semantic Memory. Links episodes to tasks for chain-level '
    'outcome attribution and semantic lifting (episode → task → project).';

COMMENT ON COLUMN synced_episodes.task_id IS
    'Phase 2: Links this episode to its parent task. '
    'Populated when sentigent_evaluate() is called with a task_id.';
