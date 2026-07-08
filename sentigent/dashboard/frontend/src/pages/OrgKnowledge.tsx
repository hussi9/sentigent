/**
 * OrgKnowledge — Layer 2 Org World Model Dashboard
 *
 * Shows what Sentigent has learned about this organization from all agent
 * activity: vocabulary, security practices, domain entities, and member contexts.
 *
 * This is the "what does this org know about itself?" view.
 */

import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/context/AuthContext";

// ── Types ────────────────────────────────────────────────────────────────────

interface VocabTerm {
  id: string;
  term: string;
  definition: string | null;
  category: string;
  confidence: number;
  occurrence_count: number;
  source: string;
  examples: string[];
}

interface SecurityPractice {
  id: string;
  practice_type: string;
  description: string;
  applies_to: string | null;
  confidence: number;
  evidence_count: number;
  source: string;
}

interface WorldEntity {
  id: string;
  entity_type: string;
  entity_name: string;
  criticality: string;
  mention_count: number;
  escalation_count: number;
  aliases: string[];
}

interface MemberContext {
  id: string;
  member_identifier: string;
  member_type: string;
  display_name: string | null;
  domains: string[];
  communication_style: string;
  risk_tolerance: string;
  typical_tools: string[];
  escalation_rate: number;
  accuracy_rate: number;
  interaction_count: number;
}

interface WorldModelSummary {
  vocab_terms: number;
  security_practices: number;
  known_entities: number;
  tracked_members: number;
}

// ── Fetch ─────────────────────────────────────────────────────────────────────

async function fetchWorldModel(orgId: string) {

  const [vocab, security, entities, members] = await Promise.all([
    supabase
      .from("org_vocabulary")
      .select("*")
      .eq("org_id", orgId)
      .order("confidence", { ascending: false })
      .limit(200),
    supabase
      .from("org_security_practices")
      .select("*")
      .eq("org_id", orgId)
      .order("evidence_count", { ascending: false })
      .limit(100),
    supabase
      .from("org_world_entities")
      .select("*")
      .eq("org_id", orgId)
      .order("mention_count", { ascending: false })
      .limit(100),
    supabase
      .from("org_member_contexts")
      .select("*")
      .eq("org_id", orgId)
      .order("interaction_count", { ascending: false })
      .limit(50),
  ]);

  return {
    vocabulary: (vocab.data ?? []) as VocabTerm[],
    security_practices: (security.data ?? []) as SecurityPractice[],
    entities: (entities.data ?? []) as WorldEntity[],
    members: (members.data ?? []) as MemberContext[],
    summary: {
      vocab_terms: vocab.data?.length ?? 0,
      security_practices: security.data?.length ?? 0,
      known_entities: entities.data?.length ?? 0,
      tracked_members: members.data?.length ?? 0,
    } as WorldModelSummary,
  };
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SummaryCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string | number;
  sub: string;
  color: string;
}) {
  return (
    <div className="bg-bg-elevated border border-border rounded-xl p-5">
      <div className={`text-3xl font-bold font-mono mb-1 ${color}`}>{value}</div>
      <div className="text-xs text-text-muted uppercase tracking-widest mb-1">{label}</div>
      <div className="text-xs text-text-subtle">{sub}</div>
    </div>
  );
}

function CategoryBadge({ cat }: { cat: string }) {
  const colors: Record<string, string> = {
    deployment: "bg-purple-500/10 text-purple-400 border-purple-500/20",
    security: "bg-red-500/10 text-red-400 border-red-500/20",
    database: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
    infrastructure: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    payments: "bg-green-500/10 text-green-400 border-green-500/20",
    general: "bg-surface text-text-muted border-border",
  };
  return (
    <span
      className={`text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-full border ${colors[cat] ?? colors.general}`}
    >
      {cat}
    </span>
  );
}

function CriticalityDot({ level }: { level: string }) {
  const colors: Record<string, string> = {
    critical: "bg-red-500",
    high: "bg-amber-500",
    medium: "bg-cyan-500",
    low: "bg-text-subtle",
  };
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${colors[level] ?? colors.medium}`}
      title={level}
    />
  );
}

function PracticeTypeBadge({ type }: { type: string }) {
  const styles: Record<string, string> = {
    forbidden: "bg-red-500/10 text-red-400 border-red-500/20",
    required: "bg-green-500/10 text-green-400 border-green-500/20",
    escalate: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    prefer: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
    avoid: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  };
  return (
    <span
      className={`text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-full border ${styles[type] ?? styles.prefer}`}
    >
      {type}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    value >= 0.8 ? "bg-green-500" : value >= 0.6 ? "bg-amber-500" : "bg-text-subtle";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-surface rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] font-mono text-text-muted w-7 text-right">{pct}%</span>
    </div>
  );
}

function RiskBadge({ risk }: { risk: string }) {
  const styles: Record<string, string> = {
    conservative: "text-green-400 bg-green-500/10 border-green-500/20",
    medium: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20",
    aggressive: "text-red-400 bg-red-500/10 border-red-500/20",
    unknown: "text-text-muted bg-surface border-border",
  };
  return (
    <span
      className={`text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-full border ${styles[risk] ?? styles.unknown}`}
    >
      {risk}
    </span>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="w-12 h-12 rounded-xl bg-bg-elevated border border-border flex items-center justify-center mb-4">
        <span className="text-text-subtle text-xl">◌</span>
      </div>
      <p className="text-text-muted text-sm max-w-xs">{message}</p>
      <p className="text-text-subtle text-xs mt-2">
        World model builds automatically from agent activity.
        More agent tasks = richer org knowledge.
      </p>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function OrgKnowledge() {
  const { membership } = useAuth();
  const orgId = membership?.org_id ?? "";

  const { data, isLoading, error } = useQuery({
    queryKey: ["org-world-model", orgId],
    queryFn: () => fetchWorldModel(orgId),
    enabled: !!orgId,
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 rounded-full border-2 border-accent/30 border-t-accent animate-spin" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-8 text-red-400 text-sm">
        Failed to load org world model. Layer 2 (Supabase) may not be configured.
      </div>
    );
  }

  const { vocabulary, security_practices, entities, members, summary } = data;

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-10">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <div className="w-2 h-2 rounded-full bg-accent animate-pulse" />
          <span className="text-xs font-mono text-accent uppercase tracking-widest">
            Layer 2 — Org World Model
          </span>
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-text-primary mb-2">
          What Sentigent knows about your org
        </h1>
        <p className="text-text-muted text-sm max-w-2xl leading-relaxed">
          Built automatically from every agent interaction: policies, conversations,
          security incidents, and individual patterns. This is the context that makes
          judgment org-specific instead of generic.
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <SummaryCard
          label="Vocabulary terms"
          value={summary.vocab_terms}
          sub="org-specific lingo observed"
          color="text-purple-400"
        />
        <SummaryCard
          label="Security practices"
          value={summary.security_practices}
          sub="inferred from policy activity"
          color="text-red-400"
        />
        <SummaryCard
          label="Known entities"
          value={summary.known_entities}
          sub="services, databases, systems"
          color="text-cyan-400"
        />
        <SummaryCard
          label="Member profiles"
          value={summary.tracked_members}
          sub="individual interaction patterns"
          color="text-green-400"
        />
      </div>

      {/* Vocabulary */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Org Vocabulary</h2>
            <p className="text-xs text-text-muted mt-0.5">
              Terms this org uses that agents now understand in context
            </p>
          </div>
          <span className="text-xs font-mono text-text-subtle">
            {vocabulary.length} terms
          </span>
        </div>

        {vocabulary.length === 0 ? (
          <EmptyState message="No vocabulary captured yet. Starts building from the first 50 agent tasks." />
        ) : (
          <div className="bg-bg-elevated border border-border rounded-xl overflow-hidden">
            <div className="grid grid-cols-[1fr_1fr_120px_90px] gap-0 px-4 py-2 border-b border-border text-[10px] font-mono text-text-subtle uppercase tracking-widest">
              <span>Term</span>
              <span>Definition / Examples</span>
              <span>Category</span>
              <span>Confidence</span>
            </div>
            <div className="divide-y divide-border">
              {vocabulary.slice(0, 50).map((v) => (
                <div
                  key={v.id}
                  className="grid grid-cols-[1fr_1fr_120px_90px] gap-0 px-4 py-3 items-start hover:bg-surface/50 transition-colors"
                >
                  <div>
                    <span className="font-mono text-sm text-text-primary">{v.term}</span>
                    <div className="text-[10px] text-text-subtle mt-0.5">
                      {v.occurrence_count}× observed · {v.source}
                    </div>
                  </div>
                  <div className="pr-4">
                    {v.definition ? (
                      <p className="text-xs text-text-secondary leading-relaxed">{v.definition}</p>
                    ) : v.examples?.length > 0 ? (
                      <p className="text-xs text-text-subtle italic leading-relaxed truncate">
                        "{v.examples[0]}"
                      </p>
                    ) : (
                      <span className="text-xs text-text-subtle">No definition yet</span>
                    )}
                  </div>
                  <div>
                    <CategoryBadge cat={v.category} />
                  </div>
                  <div>
                    <ConfidenceBar value={v.confidence} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Security Practices */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Security Practices</h2>
            <p className="text-xs text-text-muted mt-0.5">
              Inferred from what gets blocked, escalated, or approved over time
            </p>
          </div>
          <span className="text-xs font-mono text-text-subtle">
            {security_practices.length} practices
          </span>
        </div>

        {security_practices.length === 0 ? (
          <EmptyState message="No security practices inferred yet. Builds from policy violations and escalations." />
        ) : (
          <div className="space-y-2">
            {security_practices.map((p) => (
              <div
                key={p.id}
                className="bg-bg-elevated border border-border rounded-xl px-5 py-4 flex items-start gap-4"
              >
                <PracticeTypeBadge type={p.practice_type} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-text-primary leading-relaxed">{p.description}</p>
                  <div className="flex items-center gap-3 mt-1.5">
                    {p.applies_to && (
                      <span className="text-[10px] font-mono text-text-subtle">
                        context: {p.applies_to}
                      </span>
                    )}
                    <span className="text-[10px] font-mono text-text-subtle">
                      {p.evidence_count}× observed · {p.source}
                    </span>
                  </div>
                </div>
                <div className="w-20 shrink-0">
                  <ConfidenceBar value={p.confidence} />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* World Entities */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Domain Entities</h2>
            <p className="text-xs text-text-muted mt-0.5">
              Services, databases, systems — with automatic criticality scoring
            </p>
          </div>
          <span className="text-xs font-mono text-text-subtle">
            {entities.length} entities
          </span>
        </div>

        {entities.length === 0 ? (
          <EmptyState message="No entities detected yet. Extracted from service names, database references, and tool paths." />
        ) : (
          <div className="bg-bg-elevated border border-border rounded-xl overflow-hidden">
            <div className="grid grid-cols-[auto_1fr_100px_80px_80px_80px] gap-0 px-4 py-2 border-b border-border text-[10px] font-mono text-text-subtle uppercase tracking-widest">
              <span className="w-8" />
              <span>Entity</span>
              <span>Type</span>
              <span>Criticality</span>
              <span className="text-right">Mentions</span>
              <span className="text-right">Escalations</span>
            </div>
            <div className="divide-y divide-border">
              {entities.slice(0, 60).map((e) => (
                <div
                  key={e.id}
                  className="grid grid-cols-[auto_1fr_100px_80px_80px_80px] gap-0 px-4 py-3 items-center hover:bg-surface/50 transition-colors"
                >
                  <div className="w-8 flex justify-center">
                    <CriticalityDot level={e.criticality} />
                  </div>
                  <div>
                    <span className="font-mono text-sm text-text-primary">{e.entity_name}</span>
                    {e.aliases?.length > 0 && (
                      <div className="text-[10px] text-text-subtle mt-0.5">
                        aka: {e.aliases.slice(0, 3).join(", ")}
                      </div>
                    )}
                  </div>
                  <div>
                    <CategoryBadge cat={e.entity_type} />
                  </div>
                  <div className="text-xs font-mono text-text-muted capitalize">
                    {e.criticality}
                  </div>
                  <div className="text-right font-mono text-sm text-text-secondary">
                    {e.mention_count}
                  </div>
                  <div
                    className={`text-right font-mono text-sm ${
                      e.escalation_count > 0 ? "text-amber-400" : "text-text-subtle"
                    }`}
                  >
                    {e.escalation_count}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Member Contexts */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Member Contexts</h2>
            <p className="text-xs text-text-muted mt-0.5">
              Per-person communication style, domain expertise, and risk tolerance
            </p>
          </div>
          <span className="text-xs font-mono text-text-subtle">
            {members.length} members
          </span>
        </div>

        {members.length === 0 ? (
          <EmptyState message="No member profiles yet. Built from individual agent interactions and conversation patterns." />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {members.map((m) => (
              <div
                key={m.id}
                className="bg-bg-elevated border border-border rounded-xl p-5 space-y-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-mono text-sm text-text-primary truncate max-w-[220px]">
                      {m.display_name ?? m.member_identifier}
                    </div>
                    {m.display_name && (
                      <div className="text-[10px] text-text-subtle font-mono mt-0.5">
                        {m.member_identifier}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-[10px] font-mono text-text-subtle uppercase px-2 py-0.5 bg-surface rounded-full border border-border">
                      {m.member_type}
                    </span>
                    <RiskBadge risk={m.risk_tolerance} />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="text-[10px] font-mono text-text-subtle uppercase tracking-wider mb-1">
                      Domains
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {m.domains.slice(0, 4).map((d) => (
                        <CategoryBadge key={d} cat={d} />
                      ))}
                      {m.domains.length === 0 && (
                        <span className="text-xs text-text-subtle">Unknown</span>
                      )}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] font-mono text-text-subtle uppercase tracking-wider mb-1">
                      Top tools
                    </div>
                    <div className="text-xs text-text-secondary font-mono">
                      {m.typical_tools.slice(0, 3).join(", ") || "—"}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3 pt-2 border-t border-border">
                  <div>
                    <div className="text-[10px] font-mono text-text-subtle mb-1">Style</div>
                    <div className="text-xs font-mono text-text-secondary capitalize">
                      {m.communication_style}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] font-mono text-text-subtle mb-1">Escalation</div>
                    <div
                      className={`text-xs font-mono ${
                        m.escalation_rate > 0.2 ? "text-amber-400" : "text-green-400"
                      }`}
                    >
                      {(m.escalation_rate * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] font-mono text-text-subtle mb-1">Accuracy</div>
                    <div
                      className={`text-xs font-mono ${
                        m.accuracy_rate > 0.85 ? "text-green-400" : "text-amber-400"
                      }`}
                    >
                      {(m.accuracy_rate * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>

                <div className="text-[10px] font-mono text-text-subtle">
                  {m.interaction_count} interactions recorded
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Footer note */}
      <div className="border-t border-border pt-6">
        <p className="text-xs text-text-subtle leading-relaxed max-w-2xl">
          <strong className="text-text-muted">How this is built:</strong> Sentigent observes
          every agent task, policy violation, escalation, and outcome. Vocabulary is extracted
          from task text and conversations. Security practices are inferred from what gets
          blocked or escalated over time. Entities are detected from file paths, service names,
          and database references. Member contexts build from repeated interaction patterns.
          Everything here can be manually curated in org settings.
        </p>
      </div>
    </div>
  );
}
