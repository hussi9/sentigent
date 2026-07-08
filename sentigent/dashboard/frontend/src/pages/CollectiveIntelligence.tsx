import { Globe, Network, TrendingUp, Users, Shield, Zap, Lock } from "lucide-react";
import { useCollective, useCollectivePatterns } from "@/api/hooks";
import { Card, CardHeader, CardTitle, CardBody, StatCard, ActionBadge, Badge } from "@/components/ui";
import type { Layer3Pattern } from "@/types";

function ConfidenceBar({ rate }: { rate: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-bg-elevated overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{
            width: `${rate * 100}%`,
            backgroundColor: rate >= 0.8 ? "#22c55e" : rate >= 0.6 ? "#f59e0b" : "#ef4444",
          }}
        />
      </div>
      <span className="text-xs text-muted w-10 text-right">{(rate * 100).toFixed(0)}%</span>
    </div>
  );
}

function PatternRow({ pattern }: { pattern: Layer3Pattern }) {
  return (
    <tr className="border-b border-bg-border/50 hover:bg-bg-hover transition-colors">
      <td className="px-4 py-3 font-mono text-xs text-white/80">{pattern.pattern_name}</td>
      <td className="px-4 py-3"><ActionBadge action={pattern.learned_action} /></td>
      <td className="px-4 py-3 w-40"><ConfidenceBar rate={pattern.success_rate} /></td>
      <td className="px-4 py-3 text-xs text-center">
        <span className="text-white/80">{pattern.contributing_org_count}</span>
        {pattern.contributing_org_count >= 5 && (
          <span className="ml-1.5 text-[10px] text-success">verified</span>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-muted">{pattern.sample_size.toLocaleString()}</td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {(pattern.industry_tags ?? []).slice(0, 3).map((tag) => (
            <Badge key={tag} variant="muted" size="sm">{tag}</Badge>
          ))}
        </div>
      </td>
    </tr>
  );
}

export function CollectiveIntelligence() {
  const { data: collectiveData } = useCollective();
  const { data: patternsData } = useCollectivePatterns();

  const stats = collectiveData?.collective;
  const patterns = patternsData?.patterns ?? [];

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      {/* Hero */}
      <div className="p-6 rounded-xl bg-gradient-to-br from-accent/10 to-transparent border border-accent/20">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-10 h-10 rounded-xl bg-accent/20 border border-accent/30 flex items-center justify-center">
            <Globe size={18} className="text-accent-light" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-white">Layer 3 — Collective Intelligence</h2>
            <p className="text-xs text-muted">Anonymized cross-org patterns shared across the network</p>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-4 mt-4">
          <div className="text-center">
            <div className="text-xs text-muted mb-1 uppercase tracking-wider">Privacy</div>
            <div className="flex items-center justify-center gap-1.5 text-success text-xs font-medium">
              <Lock size={12} />
              Fully anonymized
            </div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted mb-1 uppercase tracking-wider">Contribution</div>
            <div className="flex items-center justify-center gap-1.5 text-accent-light text-xs font-medium">
              <Zap size={12} />
              Auto on sync
            </div>
          </div>
          <div className="text-center">
            <div className="text-xs text-muted mb-1 uppercase tracking-wider">Benefit</div>
            <div className="flex items-center justify-center gap-1.5 text-info text-xs font-medium">
              <TrendingUp size={12} />
              Faster learning
            </div>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Pool Size"
          value={stats?.pool_size ?? "—"}
          sub="patterns in collective"
          color="accent"
          icon={<Network size={14} />}
        />
        <StatCard
          label="Avg Success Rate"
          value={stats ? `${(stats.pool_avg_success_rate * 100).toFixed(1)}%` : "—"}
          sub="across all patterns"
          color="success"
          icon={<TrendingUp size={14} />}
        />
        <StatCard
          label="Multi-Org Patterns"
          value={stats?.multi_org_patterns ?? "—"}
          sub="confirmed cross-org"
          color="accent"
          icon={<Shield size={14} />}
        />
        <StatCard
          label="Opted-In Profiles"
          value={stats?.opted_in_profiles?.length ?? "—"}
          sub="contributing profiles"
          color="accent"
          icon={<Users size={14} />}
        />
      </div>

      {/* Opted-in profiles */}
      {(stats?.opted_in_profiles?.length ?? 0) > 0 && (
        <Card>
          <CardHeader>
            <CardTitle icon={<Users size={14} />}>Contributing Profiles</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="flex flex-wrap gap-2">
              {(stats?.opted_in_profiles ?? []).map((p) => (
                <div
                  key={p}
                  className="px-3 py-1.5 rounded-full bg-success-dim border border-success/20 text-xs text-success flex items-center gap-1.5"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-success" />
                  {p}
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Pattern Pool Table */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Network size={14} />}>Cross-Org Pattern Pool</CardTitle>
          <Badge variant="accent">{patterns.length} patterns</Badge>
        </CardHeader>
        {!patterns.length ? (
          <CardBody>
            <div className="text-center py-8 text-xs text-muted">
              <Globe size={24} className="mx-auto mb-2 opacity-30" />
              <p>No collective patterns available yet.</p>
              <p className="mt-1">Patterns appear once multiple orgs contribute similar behaviors.</p>
            </div>
          </CardBody>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-bg-border">
                  {["Pattern", "Learned Action", "Success Rate", "Contributing Orgs", "Sample Size", "Tags"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left text-muted font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {patterns.map((p) => <PatternRow key={p.pattern_name} pattern={p} />)}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* How It Works */}
      <Card>
        <CardHeader>
          <CardTitle>How Collective Intelligence Works</CardTitle>
        </CardHeader>
        <CardBody>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              {
                step: "1",
                title: "Local Learning",
                desc: "Each agent builds its own judgment score from its own decisions and outcomes.",
                color: "text-accent-light",
              },
              {
                step: "2",
                title: "Org Contribution",
                desc: "When Layer 2 syncs, your anonymized patterns are contributed to the collective pool (no task content, no PII).",
                color: "text-info",
              },
              {
                step: "3",
                title: "Network Benefit",
                desc: "Your agents get access to patterns validated by N organizations — much faster than learning from scratch.",
                color: "text-success",
              },
            ].map((item) => (
              <div key={item.step} className="p-4 rounded-lg bg-bg-elevated border border-bg-border">
                <div className={`text-lg font-bold ${item.color} mb-2`}>Step {item.step}</div>
                <div className="text-sm font-semibold text-white mb-1">{item.title}</div>
                <p className="text-xs text-muted">{item.desc}</p>
              </div>
            ))}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
