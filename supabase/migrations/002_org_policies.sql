-- ─────────────────────────────────────────────────────────────
-- Sentigent Layer 2 — Org-wide policy enforcement
-- Run this in the Supabase SQL Editor
-- ─────────────────────────────────────────────────────────────

-- ── org_policies ─────────────────────────────────────────────
-- Org admin configures rules here. All agents in the org
-- automatically pull and enforce these policies.
--
-- enforce_action values:
--   block    → hard block the tool call (agent cannot proceed)
--   escalate → block + require human confirmation
--   slow_down → approve but warn the agent
--   enrich   → approve but ask agent to gather more context first
--
-- trigger_tool: 'Bash', 'Write', 'Edit', '*' (any tool)
-- trigger_pattern: regex matched against the tool input
-- profile_override: if set, only agents with this profile see the policy

CREATE TABLE IF NOT EXISTS org_policies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id text NOT NULL,
    policy_name text NOT NULL,
    description text DEFAULT '',
    trigger_tool text DEFAULT '*',
    trigger_pattern text DEFAULT '',
    profile_override text DEFAULT '',      -- empty = applies to all profiles
    enforce_action text NOT NULL DEFAULT 'slow_down',
    enforce_reason text DEFAULT '',
    severity text DEFAULT 'medium',        -- low, medium, high, critical
    is_active boolean DEFAULT true,
    created_by text DEFAULT '',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    trigger_count integer DEFAULT 0,
    last_triggered timestamptz,
    UNIQUE (org_id, policy_name)
);

-- ── policy_violations ─────────────────────────────────────────
-- Log of every time a policy fired against an agent action.
-- Used for compliance reporting and proof-of-value.

CREATE TABLE IF NOT EXISTS policy_violations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id text NOT NULL,
    agent_id text NOT NULL,
    policy_name text NOT NULL,
    task text DEFAULT '',
    tool_name text DEFAULT '',
    enforced_action text DEFAULT '',
    confirmed_correct boolean,             -- set when outcome recorded
    timestamp timestamptz DEFAULT now()
);

-- ── layer3_shared_patterns ────────────────────────────────────
-- Cross-org intelligence (Layer 3).
-- Anonymized patterns contributed by orgs, surfaced to all.
-- Orgs opt in to contributing; all orgs receive.
-- No org_id stored — fully anonymized at contribution time.

CREATE TABLE IF NOT EXISTS layer3_shared_patterns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_name text NOT NULL,
    learned_action text NOT NULL,
    success_rate real NOT NULL,
    sample_size integer NOT NULL,
    contributing_org_count integer DEFAULT 1,  -- how many orgs contributed
    industry_tags text[] DEFAULT '{}',         -- e.g. {'fintech', 'healthcare'}
    created_at timestamptz DEFAULT now(),
    last_reinforced timestamptz DEFAULT now(),
    UNIQUE (pattern_name)
);

-- ── Indexes ───────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_org_policies_org
    ON org_policies(org_id, is_active);

CREATE INDEX IF NOT EXISTS idx_policy_violations_org
    ON policy_violations(org_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_policy_violations_agent
    ON policy_violations(agent_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_layer3_patterns_action
    ON layer3_shared_patterns(learned_action, success_rate DESC);

-- ── Seed default policies for any org ────────────────────────
-- These are sensible defaults every org should have.
-- Replace 'YOUR_ORG_ID' with your org_id (e.g. 'hussi')

-- INSERT INTO org_policies (org_id, policy_name, description, trigger_tool, trigger_pattern, enforce_action, enforce_reason, severity, created_by)
-- VALUES
--   ('YOUR_ORG_ID', 'no_force_push',
--    'Block force pushes to prevent overwriting upstream history',
--    'Bash', 'push --force|push -f', 'block',
--    'Force pushing can overwrite others work. Use --force-with-lease.',
--    'critical', 'admin'),
--
--   ('YOUR_ORG_ID', 'review_before_deploy',
--    'Escalate all deploy/publish/release for human review',
--    'Bash', 'deploy|publish|npm publish|twine upload|heroku|kubectl apply',
--    'escalate', 'Deploy requires human sign-off.', 'high', 'admin'),
--
--   ('YOUR_ORG_ID', 'protect_env_files',
--    'Slow down writes to credential/env files',
--    'Write', '\.env$|credentials|\.pem$|\.key$|secrets',
--    'slow_down', 'Writing to credential files — verify intent.', 'high', 'admin');
