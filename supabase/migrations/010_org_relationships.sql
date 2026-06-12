-- Phase 3: Context Assembly — Org Relationships Table
-- Entity-entity and member-entity relationship graph for the org brain.
-- Used by ContextAssembler to surface ownership, dependency, and approval chains.

-- ── org_relationships ─────────────────────────────────────────────────────────
-- One row per directed relationship edge in the org knowledge graph.
-- Examples:
--   auth/middleware.py  OWNED_BY   alice@company.com
--   payment-service     DEPENDS_ON  postgres-prod
--   bob@company.com     APPROVES   auth/middleware.py

CREATE TABLE IF NOT EXISTS org_relationships (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          TEXT NOT NULL,
    from_entity     TEXT NOT NULL,
    from_type       TEXT NOT NULL
                        CHECK (from_type IN ('file', 'service', 'member', 'team', 'database', 'infra')),
    relationship    TEXT NOT NULL
                        CHECK (relationship IN (
                            'DEPENDS_ON', 'REFERENCED_BY', 'OWNED_BY',
                            'APPROVES', 'REVIEWS', 'DEPLOYED_WITH',
                            'CALLS', 'STORES_IN', 'TRIGGERS'
                        )),
    to_entity       TEXT NOT NULL,
    to_type         TEXT NOT NULL
                        CHECK (to_type IN ('file', 'service', 'member', 'team', 'database', 'infra')),
    weight          FLOAT NOT NULL DEFAULT 1.0,     -- relationship strength (0.0–1.0)
    metadata        JSONB NOT NULL DEFAULT '{}',    -- arbitrary extra context
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One relationship type between two entities per org
    UNIQUE (org_id, from_entity, relationship, to_entity)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_org_relationships_org_from
    ON org_relationships (org_id, from_entity);

CREATE INDEX IF NOT EXISTS idx_org_relationships_org_to
    ON org_relationships (org_id, to_entity);

CREATE INDEX IF NOT EXISTS idx_org_relationships_org_type
    ON org_relationships (org_id, relationship);

-- ── Row Level Security ────────────────────────────────────────────────────────

ALTER TABLE org_relationships ENABLE ROW LEVEL SECURITY;

CREATE POLICY "org_relationships_select_policy" ON org_relationships
    FOR SELECT
    USING (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "org_relationships_insert_policy" ON org_relationships
    FOR INSERT
    WITH CHECK (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "org_relationships_update_policy" ON org_relationships
    FOR UPDATE
    USING (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid()
        )
    );

-- ── auto-update updated_at ────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_org_relationships_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER org_relationships_updated_at
    BEFORE UPDATE ON org_relationships
    FOR EACH ROW
    EXECUTE FUNCTION update_org_relationships_updated_at();

-- ── Comments ──────────────────────────────────────────────────────────────────

COMMENT ON TABLE org_relationships IS
    'Phase 3: Org Brain entity relationship graph. '
    'Used by ContextAssembler to surface ownership, dependency, and approval chains '
    'for domain-aware evaluation context. Edges: file→service→member→team.';

COMMENT ON COLUMN org_relationships.from_type IS
    'Type of the source entity: file, service, member, team, database, infra';

COMMENT ON COLUMN org_relationships.relationship IS
    'Edge type: DEPENDS_ON, OWNED_BY, APPROVES, REVIEWS, DEPLOYED_WITH, etc.';

COMMENT ON COLUMN org_relationships.weight IS
    'Relationship strength 0.0–1.0. Higher = more direct/certain. '
    'Inferred from co-occurrence in episodes (auto) or set explicitly (manual).';
