-- ─────────────────────────────────────────────────────────────────────────────
-- Sentigent — Multi-Tenant Row Level Security (RLS)
-- Run this in the Supabase SQL Editor AFTER all prior migrations.
--
-- ISOLATION MODEL:
--   - Each org is completely isolated. Org A cannot see Org B's episodes,
--     policies, patterns, profiles, or violations — at the database level.
--   - Within an org, all agents share policies and profiles (org governance).
--   - Individual agent episodes are visible to any member of the same org.
--   - layer3_shared_patterns is anonymized: readable by all, write-restricted.
--
-- HOW IT WORKS:
--   1. Each org is identified by a UUID stored in the 'org_id' column.
--   2. Applications send the claim 'app.current_org_id' via SET LOCAL or
--      via a JWT claim ('org_id') when using per-org API keys.
--   3. RLS policies reject queries where the row's org_id != the current org.
--   4. The service role key bypasses RLS (for admin/migration tasks only).
--   5. Agent API keys should be org-scoped anon keys, NOT the service role key.
--
-- SETUP FOR NEW ORG:
--   1. Create a Supabase user for the org.
--   2. Issue an anon key scoped to that org.
--   3. Include 'org_id' in the JWT payload.
--   4. Agents connect using that key — RLS enforces isolation automatically.
-- ─────────────────────────────────────────────────────────────────────────────


-- ── Helper: extract org_id from JWT or local setting ────────────────────────
-- Agents can identify themselves via:
--   a) JWT claim: the 'org_id' field in a Supabase auth JWT
--   b) Session variable: SET LOCAL app.current_org_id = '<uuid>'

CREATE OR REPLACE FUNCTION current_org_id() RETURNS text AS $$
DECLARE
    jwt_org_id text;
    setting_org_id text;
BEGIN
    -- Try JWT claim first (used with per-org API keys)
    BEGIN
        jwt_org_id := (auth.jwt() ->> 'org_id');
    EXCEPTION WHEN OTHERS THEN
        jwt_org_id := NULL;
    END;

    IF jwt_org_id IS NOT NULL AND jwt_org_id != '' THEN
        RETURN jwt_org_id;
    END IF;

    -- Fall back to session variable (used by server-side SDK calls)
    BEGIN
        setting_org_id := current_setting('app.current_org_id', TRUE);
    EXCEPTION WHEN OTHERS THEN
        setting_org_id := NULL;
    END;

    RETURN COALESCE(setting_org_id, '');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;


-- ── Enable RLS on all tables ─────────────────────────────────────────────────

-- synced_episodes
ALTER TABLE IF EXISTS synced_episodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS synced_episodes FORCE ROW LEVEL SECURITY;

-- org_patterns
ALTER TABLE IF EXISTS org_patterns ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS org_patterns FORCE ROW LEVEL SECURITY;

-- org_baselines
ALTER TABLE IF EXISTS org_baselines ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS org_baselines FORCE ROW LEVEL SECURITY;

-- org_policies
ALTER TABLE IF EXISTS org_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS org_policies FORCE ROW LEVEL SECURITY;

-- policy_violations
ALTER TABLE IF EXISTS policy_violations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS policy_violations FORCE ROW LEVEL SECURITY;

-- org_profiles
ALTER TABLE IF EXISTS org_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS org_profiles FORCE ROW LEVEL SECURITY;

-- agent_profile_assignments
ALTER TABLE IF EXISTS agent_profile_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS agent_profile_assignments FORCE ROW LEVEL SECURITY;

-- layer3_shared_patterns (public read, restricted write)
ALTER TABLE IF EXISTS layer3_shared_patterns ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS layer3_shared_patterns FORCE ROW LEVEL SECURITY;


-- ── RLS Policies: synced_episodes ────────────────────────────────────────────

DROP POLICY IF EXISTS "org_isolation_read"  ON synced_episodes;
DROP POLICY IF EXISTS "org_isolation_write" ON synced_episodes;

CREATE POLICY "org_isolation_read" ON synced_episodes
    FOR SELECT TO anon, authenticated
    USING (org_id::text = current_org_id());

CREATE POLICY "org_isolation_write" ON synced_episodes
    FOR INSERT TO anon, authenticated
    WITH CHECK (org_id::text = current_org_id());


-- ── RLS Policies: org_patterns ───────────────────────────────────────────────

DROP POLICY IF EXISTS "org_isolation_read"   ON org_patterns;
DROP POLICY IF EXISTS "org_isolation_write"  ON org_patterns;
DROP POLICY IF EXISTS "org_isolation_update" ON org_patterns;

CREATE POLICY "org_isolation_read" ON org_patterns
    FOR SELECT TO anon, authenticated
    USING (org_id::text = current_org_id());

CREATE POLICY "org_isolation_write" ON org_patterns
    FOR INSERT TO anon, authenticated
    WITH CHECK (org_id::text = current_org_id());

CREATE POLICY "org_isolation_update" ON org_patterns
    FOR UPDATE TO anon, authenticated
    USING (org_id::text = current_org_id())
    WITH CHECK (org_id::text = current_org_id());


-- ── RLS Policies: org_baselines ──────────────────────────────────────────────

DROP POLICY IF EXISTS "org_isolation_read"   ON org_baselines;
DROP POLICY IF EXISTS "org_isolation_write"  ON org_baselines;
DROP POLICY IF EXISTS "org_isolation_upsert" ON org_baselines;

CREATE POLICY "org_isolation_read" ON org_baselines
    FOR SELECT TO anon, authenticated
    USING (org_id::text = current_org_id());

CREATE POLICY "org_isolation_write" ON org_baselines
    FOR INSERT TO anon, authenticated
    WITH CHECK (org_id::text = current_org_id());

CREATE POLICY "org_isolation_upsert" ON org_baselines
    FOR UPDATE TO anon, authenticated
    USING (org_id::text = current_org_id())
    WITH CHECK (org_id::text = current_org_id());


-- ── RLS Policies: org_policies ───────────────────────────────────────────────

DROP POLICY IF EXISTS "org_isolation_read"   ON org_policies;
DROP POLICY IF EXISTS "org_isolation_write"  ON org_policies;
DROP POLICY IF EXISTS "org_isolation_update" ON org_policies;

CREATE POLICY "org_isolation_read" ON org_policies
    FOR SELECT TO anon, authenticated
    USING (org_id = current_org_id());

CREATE POLICY "org_isolation_write" ON org_policies
    FOR INSERT TO anon, authenticated
    WITH CHECK (org_id = current_org_id());

CREATE POLICY "org_isolation_update" ON org_policies
    FOR UPDATE TO anon, authenticated
    USING (org_id = current_org_id())
    WITH CHECK (org_id = current_org_id());


-- ── RLS Policies: policy_violations ─────────────────────────────────────────

DROP POLICY IF EXISTS "org_isolation_read"  ON policy_violations;
DROP POLICY IF EXISTS "org_isolation_write" ON policy_violations;

CREATE POLICY "org_isolation_read" ON policy_violations
    FOR SELECT TO anon, authenticated
    USING (org_id = current_org_id());

CREATE POLICY "org_isolation_write" ON policy_violations
    FOR INSERT TO anon, authenticated
    WITH CHECK (org_id = current_org_id());


-- ── RLS Policies: org_profiles ───────────────────────────────────────────────

DROP POLICY IF EXISTS "org_isolation_read"   ON org_profiles;
DROP POLICY IF EXISTS "org_isolation_write"  ON org_profiles;
DROP POLICY IF EXISTS "org_isolation_update" ON org_profiles;

CREATE POLICY "org_isolation_read" ON org_profiles
    FOR SELECT TO anon, authenticated
    USING (org_id = current_org_id());

CREATE POLICY "org_isolation_write" ON org_profiles
    FOR INSERT TO anon, authenticated
    WITH CHECK (org_id = current_org_id());

CREATE POLICY "org_isolation_update" ON org_profiles
    FOR UPDATE TO anon, authenticated
    USING (org_id = current_org_id())
    WITH CHECK (org_id = current_org_id());


-- ── RLS Policies: agent_profile_assignments ──────────────────────────────────

DROP POLICY IF EXISTS "org_isolation_read"   ON agent_profile_assignments;
DROP POLICY IF EXISTS "org_isolation_write"  ON agent_profile_assignments;
DROP POLICY IF EXISTS "org_isolation_upsert" ON agent_profile_assignments;

CREATE POLICY "org_isolation_read" ON agent_profile_assignments
    FOR SELECT TO anon, authenticated
    USING (org_id = current_org_id());

CREATE POLICY "org_isolation_write" ON agent_profile_assignments
    FOR INSERT TO anon, authenticated
    WITH CHECK (org_id = current_org_id());

CREATE POLICY "org_isolation_upsert" ON agent_profile_assignments
    FOR UPDATE TO anon, authenticated
    USING (org_id = current_org_id())
    WITH CHECK (org_id = current_org_id());


-- ── RLS Policies: layer3_shared_patterns ────────────────────────────────────
-- Layer 3 patterns are anonymized aggregates. All orgs can READ them,
-- but only the service role can WRITE them (server-side aggregation job).

DROP POLICY IF EXISTS "public_read" ON layer3_shared_patterns;

CREATE POLICY "public_read" ON layer3_shared_patterns
    FOR SELECT TO anon, authenticated
    USING (true);  -- All orgs can read Layer 3 patterns (fully anonymized)

-- Write is restricted to service role only (no policy = service role only).


-- ── Application-level org_id injection ──────────────────────────────────────
-- The Python SDK must call this before any query when not using JWT auth:
--
--   client.rpc('set_org_context', {'p_org_id': org_id}).execute()
--
-- This function sets the session variable used by current_org_id().

CREATE OR REPLACE FUNCTION set_org_context(p_org_id text) RETURNS void AS $$
BEGIN
    PERFORM set_config('app.current_org_id', p_org_id, TRUE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION set_org_context(text) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION current_org_id() TO anon, authenticated;


-- ── Verification query (run to confirm RLS is active) ────────────────────────
-- SELECT schemaname, tablename, rowsecurity
-- FROM pg_tables
-- WHERE tablename IN (
--     'synced_episodes', 'org_patterns', 'org_baselines',
--     'org_policies', 'policy_violations', 'org_profiles',
--     'agent_profile_assignments', 'layer3_shared_patterns'
-- );
-- All rows should show rowsecurity = true.
