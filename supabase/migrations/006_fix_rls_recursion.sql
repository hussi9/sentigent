-- =============================================================================
-- Migration 006: Fix infinite recursion in org_members RLS policy
-- =============================================================================
-- The members_self_read policy had a recursive subquery:
--   OR org_id IN (SELECT org_id FROM org_members WHERE user_id = auth.uid() ...)
-- This re-enters the same RLS policy → infinite recursion (error 42P17).
--
-- Fix: use a SECURITY DEFINER helper function that reads org_members without
-- triggering RLS (runs as function owner, not the calling user).
-- =============================================================================


-- ── 1. Security-definer helper: is current user an admin/owner of this org? ─

CREATE OR REPLACE FUNCTION is_org_admin(p_org_id UUID) RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM org_members
        WHERE user_id = auth.uid()
          AND org_id   = p_org_id
          AND role IN ('owner', 'admin')
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

GRANT EXECUTE ON FUNCTION is_org_admin(UUID) TO authenticated;


-- ── 2. Replace the recursive org_members SELECT policy ──────────────────────

DROP POLICY IF EXISTS "members_self_read" ON org_members;

CREATE POLICY "members_self_read" ON org_members
    FOR SELECT TO authenticated
    USING (
        user_id = auth.uid()      -- user reads own membership row
        OR is_org_admin(org_id)   -- org admins/owners read all rows in their org
    );


-- ── 3. Fix members_admin_write — same recursion pattern ─────────────────────

DROP POLICY IF EXISTS "members_admin_write" ON org_members;

CREATE POLICY "members_admin_write" ON org_members
    FOR INSERT TO authenticated
    WITH CHECK (is_org_admin(org_id));


-- ── 4. Fix members_admin_update ──────────────────────────────────────────────

DROP POLICY IF EXISTS "members_admin_update" ON org_members;

CREATE POLICY "members_admin_update" ON org_members
    FOR UPDATE TO authenticated
    USING (is_org_admin(org_id));


-- ── 5. Fix members_admin_delete ──────────────────────────────────────────────

DROP POLICY IF EXISTS "members_admin_delete" ON org_members;

CREATE POLICY "members_admin_delete" ON org_members
    FOR DELETE TO authenticated
    USING (
        user_id = auth.uid()    -- users can leave themselves
        OR is_org_admin(org_id) -- admins/owners can remove others
    );


-- ── 6. Fix org_invites — same recursion pattern ──────────────────────────────

DROP POLICY IF EXISTS "invites_admin_all" ON org_invites;

CREATE POLICY "invites_admin_all" ON org_invites
    FOR ALL TO authenticated
    USING    (is_org_admin(org_id))
    WITH CHECK (is_org_admin(org_id));
