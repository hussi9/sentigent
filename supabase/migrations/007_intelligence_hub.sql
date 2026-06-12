-- =============================================================================
-- Migration 007: Intelligence Hub — agent connections + signal stream
-- =============================================================================
-- Enables the central intelligence hub:
--   agent_connections  — registered agents per org
--   agent_signals      — real-time signal stream (decisions, prompts, outcomes)
--
-- The hub reads all signals across connected agents, learns collectively,
-- and feeds better intelligence back to each agent.
-- =============================================================================


-- ── 1. Agent connections ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_connections (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    agent_id        TEXT        NOT NULL,
    org_id          TEXT        NOT NULL,
    connected_at    TIMESTAMPTZ DEFAULT now(),
    last_heartbeat  TIMESTAMPTZ DEFAULT now(),
    judgment_score  NUMERIC(5,4) DEFAULT 0,
    decision_count  INT DEFAULT 0,
    capabilities    JSONB DEFAULT '[]'::jsonb,
    is_active       BOOLEAN DEFAULT TRUE,
    metadata        JSONB DEFAULT '{}'::jsonb,

    UNIQUE (agent_id, org_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_connections_org
    ON agent_connections (org_id)
    WHERE is_active = TRUE;

ALTER TABLE agent_connections ENABLE ROW LEVEL SECURITY;

CREATE POLICY "connections_org_read" ON agent_connections
    FOR SELECT TO authenticated
    USING (org_id::text = current_org_id());

CREATE POLICY "connections_org_write" ON agent_connections
    FOR ALL TO authenticated
    USING    (org_id::text = current_org_id())
    WITH CHECK (org_id::text = current_org_id());


-- ── 2. Agent signal stream ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_signals (
    id          BIGSERIAL PRIMARY KEY,
    agent_id    TEXT        NOT NULL,
    org_id      TEXT        NOT NULL,
    signal_type TEXT        NOT NULL,   -- decision | outcome | prompt | heartbeat | pattern
    payload     JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Keep only last 7 days (rolling window, managed by background cleanup or pg_partman)
CREATE INDEX IF NOT EXISTS idx_agent_signals_org_time
    ON agent_signals (org_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_signals_type
    ON agent_signals (org_id, signal_type, created_at DESC);

ALTER TABLE agent_signals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "signals_org_read" ON agent_signals
    FOR SELECT TO authenticated
    USING (org_id::text = current_org_id());

CREATE POLICY "signals_org_insert" ON agent_signals
    FOR INSERT TO authenticated
    WITH CHECK (org_id::text = current_org_id());


-- ── 3. Intelligence insights — hub-generated cross-agent findings ─────────────

CREATE TABLE IF NOT EXISTS intelligence_insights (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    org_id          TEXT        NOT NULL,
    insight_type    TEXT        NOT NULL,   -- threshold_update | pattern | regression | cross_agent
    content         TEXT        NOT NULL,
    confidence      NUMERIC(5,4) DEFAULT 0,
    supporting_data JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT now(),
    applied_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_insights_org
    ON intelligence_insights (org_id, created_at DESC);

ALTER TABLE intelligence_insights ENABLE ROW LEVEL SECURITY;

CREATE POLICY "insights_org_read" ON intelligence_insights
    FOR SELECT TO authenticated
    USING (org_id::text = current_org_id());

CREATE POLICY "insights_org_write" ON intelligence_insights
    FOR INSERT TO authenticated
    WITH CHECK (org_id::text = current_org_id());


-- ── 4. Auto-cleanup function (keep signal table lean) ────────────────────────

CREATE OR REPLACE FUNCTION cleanup_old_signals() RETURNS void AS $$
BEGIN
    DELETE FROM agent_signals
    WHERE created_at < now() - INTERVAL '7 days';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION cleanup_old_signals() TO authenticated;
