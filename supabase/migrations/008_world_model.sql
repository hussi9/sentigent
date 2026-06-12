-- =============================================================================
-- Migration 008: Org World Model — Layer 2 organizational intelligence
-- =============================================================================
-- Layer 2 now captures three things from all agent activity in the org:
--
--   1. org_vocabulary        — org-specific lingo extracted from conversations,
--                              task descriptions, and policy interactions
--   2. org_security_practices — security stances inferred from what gets blocked,
--                              escalated, or approved over time
--   3. org_world_entities    — services, databases, teams, and systems the org
--                              mentions repeatedly (with criticality tags)
--   4. org_member_contexts   — per-person communication style, domain expertise,
--                              risk tolerance, and vocabulary
--
-- These four tables together form the "world model" for the org. Before every
-- judgment, the engine queries this model to enrich its context with org-specific
-- knowledge. Without it, judgment is generic. With it, judgment is contextual.
-- =============================================================================

-- ─── 1. ORG VOCABULARY ──────────────────────────────────────────────────────
-- Org-specific terms extracted from interactions.
-- "deploy" might mean "staging first, then prod" in this org.
-- "ship it" might mean "merge without review" or "full release process".
-- These are captured automatically and can be manually curated.

CREATE TABLE IF NOT EXISTS org_vocabulary (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    term        TEXT        NOT NULL,
    definition  TEXT,                                     -- what this term means in this org
    examples    TEXT[]      NOT NULL DEFAULT '{}',        -- example usages observed
    category    TEXT        NOT NULL DEFAULT 'general',   -- 'deployment', 'security', 'infrastructure', 'process', 'domain'
    confidence  REAL        NOT NULL DEFAULT 0.5,         -- 0.0–1.0, grows with occurrences
    source      TEXT        NOT NULL DEFAULT 'observed',  -- 'observed' | 'inferred' | 'manual'
    occurrence_count INT    NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(org_id, term)
);

CREATE INDEX idx_vocab_org         ON org_vocabulary(org_id);
CREATE INDEX idx_vocab_org_cat     ON org_vocabulary(org_id, category);
CREATE INDEX idx_vocab_confidence  ON org_vocabulary(org_id, confidence DESC);

-- ─── 2. ORG SECURITY PRACTICES ──────────────────────────────────────────────
-- Security stances inferred from what gets blocked, escalated, or approved.
-- "This org always requires PR review before merging to main" is inferred from
-- 12 escalations for direct pushes. "Secrets never in code" from 8 blocks on
-- .env writes. These become context for every future judgment.

CREATE TABLE IF NOT EXISTS org_security_practices (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    practice_type  TEXT        NOT NULL,   -- 'required', 'forbidden', 'escalate', 'prefer', 'avoid'
    description    TEXT        NOT NULL,   -- human-readable practice statement
    applies_to     TEXT,                   -- context: 'deployment', 'database', 'auth', 'secrets', 'git'
    evidence_count INT         NOT NULL DEFAULT 1,   -- how many times observed
    confidence     REAL        NOT NULL DEFAULT 0.5,
    source         TEXT        NOT NULL DEFAULT 'observed', -- 'observed' | 'policy' | 'manual'
    policy_id      TEXT,                   -- if derived from a named policy
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_security_org      ON org_security_practices(org_id);
CREATE INDEX idx_security_type     ON org_security_practices(org_id, practice_type);
CREATE INDEX idx_security_applies  ON org_security_practices(org_id, applies_to);

-- ─── 3. ORG WORLD ENTITIES ───────────────────────────────────────────────────
-- Services, databases, teams, and systems the org mentions in agent activity.
-- "auth-service" appears in 40 tasks → marked as critical automatically.
-- "payments-db" appears with 3 escalations → marked high-criticality.
-- This gives the judgment layer structural knowledge of what matters.

CREATE TABLE IF NOT EXISTS org_world_entities (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    entity_type    TEXT        NOT NULL,   -- 'service', 'database', 'team', 'system', 'concept', 'api'
    entity_name    TEXT        NOT NULL,
    aliases        TEXT[]      NOT NULL DEFAULT '{}',   -- alternate names observed
    description    TEXT,
    criticality    TEXT        NOT NULL DEFAULT 'medium',  -- 'critical', 'high', 'medium', 'low'
    properties     JSONB       NOT NULL DEFAULT '{}',   -- flexible: owner, repo, url, etc.
    mention_count  INT         NOT NULL DEFAULT 1,
    escalation_count INT       NOT NULL DEFAULT 0,     -- times actions on this entity were escalated
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(org_id, entity_name)
);

CREATE INDEX idx_entities_org          ON org_world_entities(org_id);
CREATE INDEX idx_entities_type         ON org_world_entities(org_id, entity_type);
CREATE INDEX idx_entities_criticality  ON org_world_entities(org_id, criticality);
CREATE INDEX idx_entities_mentions     ON org_world_entities(org_id, mention_count DESC);

-- ─── 4. ORG MEMBER CONTEXTS ──────────────────────────────────────────────────
-- Per-person profile built from their interaction history.
-- "sarah@org.com" tends to use terse commands, works on auth/payments,
-- always escalates DB writes — her tasks get higher caution automatically.
-- "dev-agent-prod" has 94% accuracy on bash commands — fast-path for those.

CREATE TABLE IF NOT EXISTS org_member_contexts (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    member_identifier   TEXT        NOT NULL,  -- email or agent_id
    member_type         TEXT        NOT NULL DEFAULT 'human',  -- 'human' | 'agent'
    display_name        TEXT,
    vocabulary          TEXT[]      NOT NULL DEFAULT '{}',  -- terms this person uses frequently
    domains             TEXT[]      NOT NULL DEFAULT '{}',  -- 'backend', 'infra', 'auth', 'payments', etc.
    communication_style TEXT        NOT NULL DEFAULT 'unknown',  -- 'terse', 'verbose', 'technical', 'casual'
    risk_tolerance      TEXT        NOT NULL DEFAULT 'medium',   -- 'conservative', 'medium', 'aggressive'
    typical_tools       TEXT[]      NOT NULL DEFAULT '{}',  -- tools this person uses most
    escalation_rate     REAL        NOT NULL DEFAULT 0.0,   -- fraction of their actions that get escalated
    accuracy_rate       REAL        NOT NULL DEFAULT 0.5,   -- fraction of outcomes that are correct
    interaction_count   INT         NOT NULL DEFAULT 0,
    last_seen           TIMESTAMPTZ NOT NULL DEFAULT now(),
    properties          JSONB       NOT NULL DEFAULT '{}',  -- flexible extra fields
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(org_id, member_identifier)
);

CREATE INDEX idx_members_org   ON org_member_contexts(org_id);
CREATE INDEX idx_members_type  ON org_member_contexts(org_id, member_type);
CREATE INDEX idx_members_id    ON org_member_contexts(org_id, member_identifier);

-- ─── 5. WORLD MODEL OBSERVATION LOG ─────────────────────────────────────────
-- Tracks what was observed from each synced episode, for auditability.
-- Allows re-processing and debugging of world model extraction.

CREATE TABLE IF NOT EXISTS world_model_observations (
    id           BIGSERIAL   PRIMARY KEY,
    org_id       UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    episode_id   BIGINT      REFERENCES synced_episodes(id) ON DELETE SET NULL,
    observation_type TEXT    NOT NULL,  -- 'vocabulary', 'security', 'entity', 'member'
    extracted    JSONB       NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_observations_org  ON world_model_observations(org_id);
CREATE INDEX idx_observations_type ON world_model_observations(org_id, observation_type);

-- ─── RLS POLICIES ────────────────────────────────────────────────────────────

ALTER TABLE org_vocabulary           ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_security_practices   ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_world_entities       ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_member_contexts      ENABLE ROW LEVEL SECURITY;
ALTER TABLE world_model_observations ENABLE ROW LEVEL SECURITY;

-- Members can read their own org's world model
CREATE POLICY "org_members_read_vocabulary"
    ON org_vocabulary FOR SELECT
    USING (org_id IN (
        SELECT org_id FROM org_members WHERE user_id = auth.uid() AND status = 'active'
    ));

CREATE POLICY "org_members_read_security"
    ON org_security_practices FOR SELECT
    USING (org_id IN (
        SELECT org_id FROM org_members WHERE user_id = auth.uid() AND status = 'active'
    ));

CREATE POLICY "org_members_read_entities"
    ON org_world_entities FOR SELECT
    USING (org_id IN (
        SELECT org_id FROM org_members WHERE user_id = auth.uid() AND status = 'active'
    ));

CREATE POLICY "org_members_read_member_contexts"
    ON org_member_contexts FOR SELECT
    USING (org_id IN (
        SELECT org_id FROM org_members WHERE user_id = auth.uid() AND status = 'active'
    ));

CREATE POLICY "org_members_read_observations"
    ON world_model_observations FOR SELECT
    USING (org_id IN (
        SELECT org_id FROM org_members WHERE user_id = auth.uid() AND status = 'active'
    ));

-- Service role bypass (agent writes)
CREATE POLICY "service_role_all_vocabulary"   ON org_vocabulary           FOR ALL USING (true);
CREATE POLICY "service_role_all_security"     ON org_security_practices   FOR ALL USING (true);
CREATE POLICY "service_role_all_entities"     ON org_world_entities       FOR ALL USING (true);
CREATE POLICY "service_role_all_members"      ON org_member_contexts      FOR ALL USING (true);
CREATE POLICY "service_role_all_observations" ON world_model_observations FOR ALL USING (true);
