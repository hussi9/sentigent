-- ─────────────────────────────────────────────────────────────
-- Sentigent Layer 2 — Org-level profiles + agent assignments
-- Run this in the Supabase SQL Editor AFTER 002_org_policies.sql
-- ─────────────────────────────────────────────────────────────

-- ── org_profiles ─────────────────────────────────────────────
-- Org admins define profiles here. Profiles shape how ALL agents
-- in the org evaluate decisions (signal scoring biases, thresholds,
-- AI context hints).
--
-- role values: product_manager, security_engineer, data_analyst,
--              devops_engineer, (custom roles welcome)
--
-- value_weights: JSON object {"user_impact": 1.0, "code_safety": 0.6, ...}
-- thresholds: JSON object {"caution_threshold": 2.5, "doubt_threshold": 0.5}
-- agent_ids: JSON array ["hussain", "alex"] or [] for org-default
-- default_policies: JSON array of policy dicts to auto-seed

CREATE TABLE IF NOT EXISTS org_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id text NOT NULL,
    profile_name text NOT NULL,
    role text NOT NULL DEFAULT 'custom',
    description text DEFAULT '',
    value_weights jsonb DEFAULT '{}',
    thresholds jsonb DEFAULT '{}',
    ai_context_hint text DEFAULT '',
    agent_ids jsonb DEFAULT '[]',            -- [] means applies to all agents
    default_policies jsonb DEFAULT '[]',
    is_active boolean DEFAULT true,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),

    UNIQUE(org_id, profile_name)
);

CREATE INDEX IF NOT EXISTS idx_org_profiles_org_id
    ON org_profiles(org_id) WHERE is_active = true;


-- ── agent_profile_assignments ─────────────────────────────────
-- Maps specific agents to specific profiles.
-- An agent can only have one active profile at a time.
-- If no assignment exists, the org-default profile is used (agent_ids=[]).

CREATE TABLE IF NOT EXISTS agent_profile_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id text NOT NULL,
    agent_id text NOT NULL,
    profile_name text NOT NULL,
    assigned_at timestamptz DEFAULT now(),
    assigned_by text DEFAULT '',            -- who set this (admin agent_id)
    notes text DEFAULT '',

    UNIQUE(org_id, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_profile_assignments_lookup
    ON agent_profile_assignments(org_id, agent_id);


-- ── Trigger to update updated_at ─────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.triggers
        WHERE trigger_name = 'update_org_profiles_updated_at'
    ) THEN
        CREATE TRIGGER update_org_profiles_updated_at
            BEFORE UPDATE ON org_profiles
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;


-- ── Seed: example profiles for hussi org ─────────────────────
-- Uncomment and customize as needed:

/*
INSERT INTO org_profiles (org_id, profile_name, role, description, value_weights, thresholds, ai_context_hint)
VALUES
    (
        'd5a4b314-461a-47bc-8fc4-ddf8e369a92d',
        'product_manager',
        'product_manager',
        'PM perspective: prioritize user value, avoid over-engineering',
        '{"user_impact": 1.0, "delivery_speed": 0.8, "code_quality": 0.6}',
        '{"caution_threshold": 2.5, "doubt_threshold": 0.5}',
        'Think like a PM: prioritize user value and feature delivery. Flag over-engineering.'
    ),
    (
        'd5a4b314-461a-47bc-8fc4-ddf8e369a92d',
        'security_engineer',
        'security_engineer',
        'Security-first: strict on secrets, auth, and compliance',
        '{"security": 1.0, "compliance": 0.95, "correctness": 0.85}',
        '{"caution_threshold": 1.5, "confidence_fast_path": 0.95}',
        'Think like a security engineer: flag any secrets, auth issues, or injection risks.'
    )
ON CONFLICT (org_id, profile_name) DO NOTHING;
*/
