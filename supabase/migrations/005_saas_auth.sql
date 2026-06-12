-- =============================================================================
-- Sentigent SaaS Auth Foundation — Migration 005
-- =============================================================================
-- Adds:
--   1. org_members  — maps auth.users → organizations with roles
--   2. org_invites  — invite-token flow for bringing users into an org
--   3. Fixes TEXT org_id → UUID in org_policies, policy_violations,
--      org_profiles, agent_profile_assignments
--   4. Updated RLS: user JWT (auth.uid → org_members) AND API key (current_org_id)
--      both work transparently
-- =============================================================================


-- =============================================================================
-- 1. ORG MEMBERS (human ↔ org relationship)
-- =============================================================================

CREATE TABLE IF NOT EXISTS org_members (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role         TEXT NOT NULL DEFAULT 'member'
                 CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    invited_by   UUID REFERENCES auth.users(id),
    joined_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_org_members_user ON org_members(user_id);
CREATE INDEX IF NOT EXISTS idx_org_members_org  ON org_members(org_id);

-- RLS for org_members
ALTER TABLE org_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_members FORCE ROW LEVEL SECURITY;

-- Users can see their own membership rows
-- Admins/owners can see all members in their org
CREATE POLICY "members_self_read" ON org_members
    FOR SELECT TO authenticated
    USING (
        user_id = auth.uid()
        OR org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

-- Only owners/admins can insert (invite flow)
CREATE POLICY "members_admin_write" ON org_members
    FOR INSERT TO authenticated
    WITH CHECK (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

-- Owners/admins can update roles
CREATE POLICY "members_admin_update" ON org_members
    FOR UPDATE TO authenticated
    USING (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

-- Owners/admins can remove members, users can leave themselves
CREATE POLICY "members_admin_delete" ON org_members
    FOR DELETE TO authenticated
    USING (
        user_id = auth.uid()
        OR org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );


-- =============================================================================
-- 2. ORG INVITES
-- =============================================================================

CREATE TABLE IF NOT EXISTS org_invites (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'member'
                CHECK (role IN ('admin', 'member', 'viewer')),
    token       TEXT NOT NULL UNIQUE DEFAULT replace(gen_random_uuid()::text || gen_random_uuid()::text, '-', ''),
    invited_by  UUID REFERENCES auth.users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '7 days'),
    accepted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_org_invites_token  ON org_invites(token);
CREATE INDEX IF NOT EXISTS idx_org_invites_email  ON org_invites(email);
CREATE INDEX IF NOT EXISTS idx_org_invites_org    ON org_invites(org_id);

ALTER TABLE org_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_invites FORCE ROW LEVEL SECURITY;

-- Admins can create/read/delete invites for their org
CREATE POLICY "invites_admin_all" ON org_invites
    FOR ALL TO authenticated
    USING (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    )
    WITH CHECK (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

-- Unauthenticated users can look up invite tokens (to accept them)
CREATE POLICY "invites_token_lookup" ON org_invites
    FOR SELECT TO anon
    USING (accepted_at IS NULL AND expires_at > now());


-- =============================================================================
-- 3. FIX ORG_ID TYPES: TEXT → UUID
--    org_policies, policy_violations, org_profiles, agent_profile_assignments
-- =============================================================================

-- Drop foreign key-backed indexes before altering type
DROP INDEX IF EXISTS idx_org_policies_org;
DROP INDEX IF EXISTS idx_policy_violations_org;
DROP INDEX IF EXISTS idx_policy_violations_agent;
DROP INDEX IF EXISTS idx_org_profiles_org_id;
DROP INDEX IF EXISTS idx_agent_profile_assignments_lookup;

-- Drop existing RLS policies that reference org_id before altering column type
DROP POLICY IF EXISTS "org_isolation_read"   ON org_policies;
DROP POLICY IF EXISTS "org_isolation_write"  ON org_policies;
DROP POLICY IF EXISTS "org_isolation_update" ON org_policies;
DROP POLICY IF EXISTS "org_isolation_read"   ON policy_violations;
DROP POLICY IF EXISTS "org_isolation_write"  ON policy_violations;
DROP POLICY IF EXISTS "org_isolation_read"   ON org_profiles;
DROP POLICY IF EXISTS "org_isolation_write"  ON org_profiles;
DROP POLICY IF EXISTS "org_isolation_update" ON org_profiles;
DROP POLICY IF EXISTS "org_isolation_read"   ON agent_profile_assignments;
DROP POLICY IF EXISTS "org_isolation_write"  ON agent_profile_assignments;
DROP POLICY IF EXISTS "org_isolation_upsert" ON agent_profile_assignments;

-- Data migration: resolve slug org_ids to UUID
-- Maps known slugs → their UUIDs (resolves existing data before type change)
UPDATE org_policies      SET org_id = orgs.id::text FROM organizations orgs WHERE orgs.slug = org_id AND org_id NOT LIKE '%-%-%-%-%';
UPDATE policy_violations SET org_id = orgs.id::text FROM organizations orgs WHERE orgs.slug = org_id AND org_id NOT LIKE '%-%-%-%-%';
UPDATE org_profiles      SET org_id = orgs.id::text FROM organizations orgs WHERE orgs.slug = org_id AND org_id NOT LIKE '%-%-%-%-%';
UPDATE agent_profile_assignments SET org_id = orgs.id::text FROM organizations orgs WHERE orgs.slug = org_id AND org_id NOT LIKE '%-%-%-%-%';

-- Delete any rows whose org_id is still not a UUID (orphaned data from deleted orgs)
DELETE FROM org_policies      WHERE org_id NOT LIKE '%-%-%-%-%';
DELETE FROM policy_violations WHERE org_id NOT LIKE '%-%-%-%-%';
DELETE FROM org_profiles      WHERE org_id NOT LIKE '%-%-%-%-%';
DELETE FROM agent_profile_assignments WHERE org_id NOT LIKE '%-%-%-%-%';

-- org_policies: org_id TEXT → UUID
ALTER TABLE org_policies
    ALTER COLUMN org_id TYPE UUID USING org_id::UUID;

ALTER TABLE org_policies
    ADD CONSTRAINT fk_org_policies_org
    FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE;

-- policy_violations: org_id TEXT → UUID
ALTER TABLE policy_violations
    ALTER COLUMN org_id TYPE UUID USING org_id::UUID;

ALTER TABLE policy_violations
    ADD CONSTRAINT fk_policy_violations_org
    FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE;

-- org_profiles: org_id TEXT → UUID
ALTER TABLE org_profiles
    ALTER COLUMN org_id TYPE UUID USING org_id::UUID;

ALTER TABLE org_profiles
    ADD CONSTRAINT fk_org_profiles_org
    FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE;

-- agent_profile_assignments: org_id TEXT → UUID
ALTER TABLE agent_profile_assignments
    ALTER COLUMN org_id TYPE UUID USING org_id::UUID;

ALTER TABLE agent_profile_assignments
    ADD CONSTRAINT fk_agent_profile_assignments_org
    FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_org_policies_org
    ON org_policies(org_id, is_active);

CREATE INDEX IF NOT EXISTS idx_policy_violations_org
    ON policy_violations(org_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_policy_violations_agent
    ON policy_violations(agent_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_org_profiles_org_id
    ON org_profiles(org_id) WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_agent_profile_assignments_lookup
    ON agent_profile_assignments(org_id, agent_id);

-- Recreate RLS policies for tables that had them dropped (now with UUID org_id)
CREATE POLICY "org_isolation_read" ON org_policies
    FOR SELECT TO anon, authenticated
    USING (org_id::text = current_org_id());

CREATE POLICY "org_isolation_write" ON org_policies
    FOR INSERT TO anon, authenticated
    WITH CHECK (org_id::text = current_org_id());

CREATE POLICY "org_isolation_update" ON org_policies
    FOR UPDATE TO anon, authenticated
    USING (org_id::text = current_org_id())
    WITH CHECK (org_id::text = current_org_id());

CREATE POLICY "org_isolation_read" ON policy_violations
    FOR SELECT TO anon, authenticated
    USING (org_id::text = current_org_id());

CREATE POLICY "org_isolation_write" ON policy_violations
    FOR INSERT TO anon, authenticated
    WITH CHECK (org_id::text = current_org_id());

CREATE POLICY "org_isolation_read" ON org_profiles
    FOR SELECT TO anon, authenticated
    USING (org_id::text = current_org_id());

CREATE POLICY "org_isolation_write" ON org_profiles
    FOR INSERT TO anon, authenticated
    WITH CHECK (org_id::text = current_org_id());

CREATE POLICY "org_isolation_update" ON org_profiles
    FOR UPDATE TO anon, authenticated
    USING (org_id::text = current_org_id())
    WITH CHECK (org_id::text = current_org_id());

CREATE POLICY "org_isolation_read" ON agent_profile_assignments
    FOR SELECT TO anon, authenticated
    USING (org_id::text = current_org_id());

CREATE POLICY "org_isolation_write" ON agent_profile_assignments
    FOR INSERT TO anon, authenticated
    WITH CHECK (org_id::text = current_org_id());

CREATE POLICY "org_isolation_upsert" ON agent_profile_assignments
    FOR UPDATE TO anon, authenticated
    USING (org_id::text = current_org_id())
    WITH CHECK (org_id::text = current_org_id());


-- =============================================================================
-- 4. UPDATED current_org_id() — supports both auth methods
--    Priority: JWT org_id claim (API key auth) → session var → auth.uid() lookup
-- =============================================================================

CREATE OR REPLACE FUNCTION current_org_id() RETURNS text AS $$
DECLARE
    jwt_org_id     text;
    setting_org_id text;
    member_org_id  text;
BEGIN
    -- 1. JWT claim (used by API key / agent clients)
    BEGIN
        jwt_org_id := (auth.jwt() ->> 'org_id');
    EXCEPTION WHEN OTHERS THEN
        jwt_org_id := NULL;
    END;

    IF jwt_org_id IS NOT NULL AND jwt_org_id != '' THEN
        RETURN jwt_org_id;
    END IF;

    -- 2. Session variable (server-side SDK calls)
    BEGIN
        setting_org_id := current_setting('app.current_org_id', TRUE);
    EXCEPTION WHEN OTHERS THEN
        setting_org_id := NULL;
    END;

    IF setting_org_id IS NOT NULL AND setting_org_id != '' THEN
        RETURN setting_org_id;
    END IF;

    -- 3. Web portal users: resolve via org_members
    BEGIN
        SELECT org_id::text INTO member_org_id
        FROM org_members
        WHERE user_id = auth.uid()
        LIMIT 1;
    EXCEPTION WHEN OTHERS THEN
        member_org_id := NULL;
    END;

    RETURN COALESCE(member_org_id, '');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;


-- =============================================================================
-- 5. HELPER FUNCTION: user_org_id() for typed UUID use in RLS policies
-- =============================================================================

CREATE OR REPLACE FUNCTION user_org_id() RETURNS UUID AS $$
DECLARE
    result UUID;
BEGIN
    SELECT org_id INTO result
    FROM org_members
    WHERE user_id = auth.uid()
    LIMIT 1;
    RETURN result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

GRANT EXECUTE ON FUNCTION user_org_id() TO authenticated;


-- =============================================================================
-- 6. UPDATE ORGANIZATION RLS to allow member-based access
-- =============================================================================

DROP POLICY IF EXISTS "orgs_own_data" ON organizations;

-- Org visible to its members
CREATE POLICY "orgs_member_read" ON organizations
    FOR SELECT TO authenticated
    USING (
        id IN (SELECT org_id FROM org_members WHERE user_id = auth.uid())
        OR id::text = current_org_id()
    );

-- Owners can update their org
CREATE POLICY "orgs_owner_update" ON organizations
    FOR UPDATE TO authenticated
    USING (
        id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid() AND role = 'owner'
        )
    );


-- =============================================================================
-- 7. UPDATE API KEYS RLS to allow member-based access
-- =============================================================================

DROP POLICY IF EXISTS "api_keys_own_org" ON api_keys;

CREATE POLICY "api_keys_member_read" ON api_keys
    FOR SELECT TO authenticated
    USING (
        org_id IN (SELECT org_id FROM org_members WHERE user_id = auth.uid())
        OR org_id::text = current_org_id()
    );

CREATE POLICY "api_keys_admin_write" ON api_keys
    FOR INSERT TO authenticated
    WITH CHECK (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

CREATE POLICY "api_keys_admin_update" ON api_keys
    FOR UPDATE TO authenticated
    USING (
        org_id IN (
            SELECT org_id FROM org_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
        OR org_id::text = current_org_id()
    );


-- =============================================================================
-- 8. RPC: accept_invite — called when user signs up via invite token
-- =============================================================================

CREATE OR REPLACE FUNCTION accept_invite(p_token TEXT) RETURNS JSONB AS $$
DECLARE
    invite_row org_invites%ROWTYPE;
    result     JSONB;
BEGIN
    -- Find valid invite
    SELECT * INTO invite_row
    FROM org_invites
    WHERE token = p_token
      AND accepted_at IS NULL
      AND expires_at > now();

    IF NOT FOUND THEN
        RETURN jsonb_build_object('error', 'Invalid or expired invite token');
    END IF;

    -- Create membership
    INSERT INTO org_members (org_id, user_id, role, invited_by)
    VALUES (invite_row.org_id, auth.uid(), invite_row.role, invite_row.invited_by)
    ON CONFLICT (org_id, user_id) DO NOTHING;

    -- Mark invite accepted
    UPDATE org_invites
    SET accepted_at = now()
    WHERE id = invite_row.id;

    RETURN jsonb_build_object(
        'org_id', invite_row.org_id,
        'role', invite_row.role
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION accept_invite(text) TO authenticated;


-- =============================================================================
-- 9. RPC: create_org_with_owner — called during signup
-- =============================================================================

CREATE OR REPLACE FUNCTION create_org_with_owner(
    p_name TEXT,
    p_slug TEXT
) RETURNS JSONB AS $$
DECLARE
    new_org_id UUID;
BEGIN
    -- Create the organization
    INSERT INTO organizations (name, slug, plan)
    VALUES (p_name, p_slug, 'free')
    RETURNING id INTO new_org_id;

    -- Make the current user the owner
    INSERT INTO org_members (org_id, user_id, role)
    VALUES (new_org_id, auth.uid(), 'owner');

    RETURN jsonb_build_object('org_id', new_org_id, 'slug', p_slug);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION create_org_with_owner(text, text) TO authenticated;


-- =============================================================================
-- Verification
-- =============================================================================
-- SELECT table_name, rowsecurity FROM pg_tables
-- WHERE table_name IN ('org_members', 'org_invites', 'org_policies', 'org_profiles');
-- All should show rowsecurity = true.
