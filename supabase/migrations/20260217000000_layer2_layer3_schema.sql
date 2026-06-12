-- =============================================================================
-- Sentigent Layer 2 + Layer 3 Schema Migration
-- =============================================================================
-- Layer 1: Local SQLite (per-agent) -- stays local, no changes here
-- Layer 2: Organizational Intelligence (shared PostgreSQL via Supabase)
-- Layer 3: Collective Intelligence (privacy-preserving, cross-org)
--
-- This migration creates the complete schema for multi-agent organizational
-- learning and privacy-preserving collective intelligence.
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- ORGANIZATIONS & AUTHENTICATION
-- =============================================================================

-- Organizations table
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'team', 'enterprise')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- API keys for authentication
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL,  -- bcrypt hash, never store plaintext
    name TEXT NOT NULL,
    permissions TEXT[] NOT NULL DEFAULT ARRAY['read', 'write'],
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX idx_api_keys_org ON api_keys(org_id);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);

-- =============================================================================
-- LAYER 2 -- ORGANIZATIONAL INTELLIGENCE
-- =============================================================================

-- Synced episodes from agents (Layer 1 -> Layer 2)
CREATE TABLE synced_episodes (
    id BIGSERIAL PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    task TEXT NOT NULL,
    context JSONB NOT NULL DEFAULT '{}',
    agent_state JSONB NOT NULL DEFAULT '{}',
    signals JSONB NOT NULL DEFAULT '{}',
    decision TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    confidence_at_decision REAL DEFAULT 0.5,
    outcome TEXT,
    outcome_feedback TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(org_id, trace_id)
);

-- Indexes for performance
CREATE INDEX idx_synced_episodes_org_agent ON synced_episodes(org_id, agent_id);
CREATE INDEX idx_synced_episodes_org_created ON synced_episodes(org_id, created_at DESC);
CREATE INDEX idx_synced_episodes_outcome ON synced_episodes(org_id, outcome) WHERE outcome IS NOT NULL;
CREATE INDEX idx_synced_episodes_task_gin ON synced_episodes USING gin(to_tsvector('english', task));

-- Org-wide aggregated baselines (computed from all agents in org)
CREATE TABLE org_baselines (
    id BIGSERIAL PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    profile_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    median DOUBLE PRECISION NOT NULL DEFAULT 0,
    mean DOUBLE PRECISION NOT NULL DEFAULT 0,
    std DOUBLE PRECISION NOT NULL DEFAULT 1,
    p5 DOUBLE PRECISION DEFAULT 0,
    p25 DOUBLE PRECISION DEFAULT 0,
    p75 DOUBLE PRECISION DEFAULT 0,
    p95 DOUBLE PRECISION DEFAULT 0,
    min_observed DOUBLE PRECISION DEFAULT 0,
    max_observed DOUBLE PRECISION DEFAULT 0,
    sample_size INTEGER NOT NULL DEFAULT 0,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(org_id, profile_name, metric_name)
);
CREATE INDEX idx_org_baselines_lookup ON org_baselines(org_id, profile_name);

-- Org-wide learned patterns (promoted from cross-agent episode analysis)
CREATE TABLE org_patterns (
    id BIGSERIAL PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    profile_name TEXT NOT NULL,
    pattern_name TEXT NOT NULL,
    condition JSONB NOT NULL DEFAULT '{}',
    learned_action TEXT NOT NULL,
    success_rate REAL NOT NULL DEFAULT 0,
    sample_size INTEGER NOT NULL DEFAULT 0,
    contributing_agents TEXT[] DEFAULT ARRAY[]::TEXT[],
    last_reinforced TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active BOOLEAN NOT NULL DEFAULT true,
    UNIQUE(org_id, profile_name, pattern_name)
);

-- Baseline history for auditing and drift detection
CREATE TABLE baseline_history (
    id BIGSERIAL PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    profile_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    baseline_snapshot JSONB NOT NULL,
    sample_size INTEGER NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_baseline_history_lookup ON baseline_history(org_id, profile_name, metric_name, computed_at DESC);

-- =============================================================================
-- LAYER 3 -- COLLECTIVE INTELLIGENCE (Privacy-Preserving)
-- =============================================================================

-- Anonymous pattern fingerprints (no PII, no raw data)
CREATE TABLE collective_patterns (
    id BIGSERIAL PRIMARY KEY,
    profile_name TEXT NOT NULL,
    pattern_fingerprint TEXT NOT NULL,  -- hash of condition, not the raw data
    pattern_category TEXT NOT NULL,     -- e.g., 'anomaly_detection', 'escalation_trigger'
    aggregate_success_rate REAL NOT NULL DEFAULT 0,
    contributing_org_count INTEGER NOT NULL DEFAULT 0,
    total_sample_size INTEGER NOT NULL DEFAULT 0,
    -- Differential privacy: noise added to these values
    noisy_median DOUBLE PRECISION,
    noisy_std DOUBLE PRECISION,
    noise_epsilon REAL NOT NULL DEFAULT 1.0,  -- privacy budget
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(profile_name, pattern_fingerprint)
);
CREATE INDEX idx_collective_patterns_profile ON collective_patterns(profile_name);

-- Collective baselines (aggregated across orgs, with differential privacy)
CREATE TABLE collective_baselines (
    id BIGSERIAL PRIMARY KEY,
    profile_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    -- Noisy aggregates (differential privacy applied)
    noisy_median DOUBLE PRECISION NOT NULL DEFAULT 0,
    noisy_mean DOUBLE PRECISION NOT NULL DEFAULT 0,
    noisy_std DOUBLE PRECISION NOT NULL DEFAULT 1,
    noise_epsilon REAL NOT NULL DEFAULT 1.0,
    contributing_org_count INTEGER NOT NULL DEFAULT 0,
    total_sample_size INTEGER NOT NULL DEFAULT 0,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(profile_name, metric_name)
);

-- Org opt-in tracking for Layer 3
CREATE TABLE collective_opt_ins (
    id BIGSERIAL PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    profile_name TEXT NOT NULL,
    opted_in BOOLEAN NOT NULL DEFAULT false,
    opted_in_at TIMESTAMPTZ,
    opted_out_at TIMESTAMPTZ,
    UNIQUE(org_id, profile_name)
);

-- =============================================================================
-- ROW-LEVEL SECURITY
-- =============================================================================

-- Enable RLS on all tables
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE synced_episodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_baselines ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_patterns ENABLE ROW LEVEL SECURITY;
ALTER TABLE baseline_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE collective_opt_ins ENABLE ROW LEVEL SECURITY;

-- RLS policies: orgs can only see their own data
-- (Uses Supabase auth.uid() for JWT-based access, or custom claims for API key auth)

CREATE POLICY "orgs_own_data" ON organizations
    FOR ALL USING (id = auth.uid()::uuid);

CREATE POLICY "api_keys_own_org" ON api_keys
    FOR ALL USING (org_id = auth.uid()::uuid);

CREATE POLICY "episodes_own_org" ON synced_episodes
    FOR ALL USING (org_id = auth.uid()::uuid);

CREATE POLICY "baselines_own_org" ON org_baselines
    FOR ALL USING (org_id = auth.uid()::uuid);

CREATE POLICY "patterns_own_org" ON org_patterns
    FOR ALL USING (org_id = auth.uid()::uuid);

CREATE POLICY "history_own_org" ON baseline_history
    FOR ALL USING (org_id = auth.uid()::uuid);

CREATE POLICY "opt_ins_own_org" ON collective_opt_ins
    FOR ALL USING (org_id = auth.uid()::uuid);

-- Collective tables are read-only for all authenticated users
CREATE POLICY "collective_patterns_read" ON collective_patterns
    FOR SELECT USING (true);

CREATE POLICY "collective_baselines_read" ON collective_baselines
    FOR SELECT USING (true);

-- =============================================================================
-- FUNCTIONS FOR AGGREGATION
-- =============================================================================

-- Function to recompute org baselines from synced episodes
CREATE OR REPLACE FUNCTION compute_org_baselines(
    p_org_id UUID,
    p_profile_name TEXT
) RETURNS void AS $$
DECLARE
    rec RECORD;
BEGIN
    -- For each numeric key in episode contexts, compute statistics
    FOR rec IN
        SELECT
            key,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY (value::text)::numeric) as median,
            avg((value::text)::numeric) as mean,
            stddev_pop((value::text)::numeric) as std,
            percentile_cont(0.05) WITHIN GROUP (ORDER BY (value::text)::numeric) as p5,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY (value::text)::numeric) as p25,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY (value::text)::numeric) as p75,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY (value::text)::numeric) as p95,
            min((value::text)::numeric) as min_val,
            max((value::text)::numeric) as max_val,
            count(*) as sample_size
        FROM synced_episodes,
            jsonb_each(context) AS kv(key, value)
        WHERE org_id = p_org_id
            AND outcome IS NOT NULL
            AND jsonb_typeof(value) = 'number'
            AND key NOT IN ('is_recording', 'is_destructive', 'is_deployment',
                          'is_sensitive_file', 'consequence_severity', 'duration_ms',
                          'data_quality', 'time_pressure', 'lines_changed')
            AND created_at > now() - interval '90 days'
        GROUP BY key
        HAVING count(*) >= 10
    LOOP
        INSERT INTO org_baselines (
            org_id, profile_name, metric_name,
            median, mean, std, p5, p25, p75, p95,
            min_observed, max_observed, sample_size, computed_at
        ) VALUES (
            p_org_id, p_profile_name, rec.key,
            rec.median, rec.mean, COALESCE(rec.std, 0), rec.p5, rec.p25, rec.p75, rec.p95,
            rec.min_val, rec.max_val, rec.sample_size, now()
        )
        ON CONFLICT (org_id, profile_name, metric_name)
        DO UPDATE SET
            median = EXCLUDED.median,
            mean = EXCLUDED.mean,
            std = EXCLUDED.std,
            p5 = EXCLUDED.p5,
            p25 = EXCLUDED.p25,
            p75 = EXCLUDED.p75,
            p95 = EXCLUDED.p95,
            min_observed = EXCLUDED.min_observed,
            max_observed = EXCLUDED.max_observed,
            sample_size = EXCLUDED.sample_size,
            computed_at = EXCLUDED.computed_at;

        -- Archive to history for drift detection
        INSERT INTO baseline_history (
            org_id, profile_name, metric_name,
            baseline_snapshot, sample_size, computed_at
        ) VALUES (
            p_org_id, p_profile_name, rec.key,
            jsonb_build_object(
                'median', rec.median, 'mean', rec.mean, 'std', rec.std,
                'p5', rec.p5, 'p25', rec.p25, 'p75', rec.p75, 'p95', rec.p95
            ),
            rec.sample_size, now()
        );
    END LOOP;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to compute judgment score for an agent in an org
CREATE OR REPLACE FUNCTION get_judgment_score(
    p_org_id UUID,
    p_agent_id TEXT DEFAULT NULL
) RETURNS TABLE(total_decisions BIGINT, correct_decisions BIGINT, score NUMERIC) AS $$
BEGIN
    RETURN QUERY
    SELECT
        count(*)::BIGINT as total_decisions,
        count(*) FILTER (WHERE outcome = 'correct')::BIGINT as correct_decisions,
        CASE
            WHEN count(*) = 0 THEN 0.0::NUMERIC
            ELSE round((count(*) FILTER (WHERE outcome = 'correct'))::NUMERIC / count(*)::NUMERIC, 4)
        END as score
    FROM synced_episodes
    WHERE org_id = p_org_id
        AND (p_agent_id IS NULL OR agent_id = p_agent_id)
        AND outcome IS NOT NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to auto-update updated_at on organizations
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- VECTOR EMBEDDING SUPPORT (for future episode similarity search)
-- =============================================================================

-- Add embedding column to synced_episodes (nullable, filled async)
ALTER TABLE synced_episodes ADD COLUMN embedding vector(384);
CREATE INDEX idx_episodes_embedding ON synced_episodes
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
