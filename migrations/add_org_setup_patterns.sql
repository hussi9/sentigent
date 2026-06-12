-- Migration: org_setup_patterns table for M4 org-wide setup sharing
-- Apply via: psql $SUPABASE_DB_URL < migrations/add_org_setup_patterns.sql
-- Or via Supabase dashboard SQL editor

CREATE TABLE IF NOT EXISTS public.org_setup_patterns (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    source_agent_id TEXT NOT NULL,
    change_type TEXT NOT NULL,
    description TEXT NOT NULL,
    new_value JSONB NOT NULL,
    adoption_count INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Row-level security: orgs can only see their own patterns
ALTER TABLE public.org_setup_patterns ENABLE ROW LEVEL SECURITY;

CREATE POLICY "org_setup_patterns_org_isolation"
ON public.org_setup_patterns
FOR ALL
USING (org_id = current_setting('app.org_id', true)::UUID);

CREATE INDEX idx_org_setup_patterns_org ON public.org_setup_patterns(org_id);
CREATE INDEX idx_org_setup_patterns_change_type ON public.org_setup_patterns(change_type);
CREATE UNIQUE INDEX idx_org_setup_patterns_dedup
ON public.org_setup_patterns(org_id, source_agent_id, change_type, description);
