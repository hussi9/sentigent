import { useState } from "react";
import { toast } from "sonner";
import { TrendingUp, ShieldCheck, Target, AlertTriangle, Award, Download, CheckCircle, XCircle } from "lucide-react";
import { useProve } from "@/api/hooks";
import { Card, CardHeader, CardTitle, CardBody, StatCard, ActionBadge, SeverityBadge, Badge } from "@/components/ui";
import { ScoreTimeline } from "@/components/charts/ScoreTimeline";
import type { TimelinePoint } from "@/types";

const DAYS_OPTIONS = [7, 30, 90] as const;

function formatTime(ts: string) {
  return new Date(ts).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function VerdictCard({ verdict }: { verdict: string }) {
  const isPositive = verdict.toLowerCase().includes("well") || verdict.toLowerCase().includes("strong") || verdict.toLowerCase().includes("excellent");

  return (
    <div className={`p-4 rounded-xl border ${isPositive ? "bg-success-dim border-success/25" : "bg-warning-dim border-warning/25"}`}>
      <div className="flex items-center gap-2 mb-1">
        {isPositive
          ? <CheckCircle size={14} className="text-success" />
          : <AlertTriangle size={14} className="text-warning" />
        }
        <span className="text-xs font-semibold text-white">Assessment</span>
      </div>
      <p className="text-xs text-white/80 leading-relaxed">{verdict}</p>
    </div>
  );
}

export function ProofOfValue() {
  const [days, setDays] = useState<(typeof DAYS_OPTIONS)[number]>(90);
  const { data: prove, isLoading } = useProve(days);

  const trajectory: TimelinePoint[] = (prove?.score_trajectory ?? []).map((p) => ({
    day: p.period,
    total: p.total_rated,
    correct: Math.round(p.score * p.total_rated),
    score: p.score,
  }));

  function exportCSV() {
    if (!prove) return;
    const rows = [
      ["timestamp", "decision", "task", "reason", "confidence", "source"],
      ...(prove.top_catches ?? []).map((c) => [
        c.timestamp, c.decision, c.task.replace(/,/g, ";"), c.reason.replace(/,/g, ";"),
        (c.confidence * 100).toFixed(0) + "%", c.policy_name ?? "judgment",
      ]),
    ];
    const csv = rows.map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sentigent-catches-${days}d.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("CSV exported", { description: `${prove.top_catches.length} catches downloaded` });
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      {/* Header with period selector */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <Award size={16} className="text-accent-light" />
            Proof of Value
          </h2>
          <p className="text-xs text-muted mt-0.5">
            Quantified impact of Sentigent judgment over time
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-bg-border overflow-hidden">
            {DAYS_OPTIONS.map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  days === d
                    ? "bg-accent/20 text-accent-light border-r border-accent/20 last:border-r-0"
                    : "text-muted hover:text-white hover:bg-bg-elevated border-r border-bg-border last:border-r-0"
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
          <button
            onClick={exportCSV}
            title="Export CSV"
            className="btn btn-ghost border border-bg-border gap-1.5"
          >
            <Download size={12} />
            Export
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-24 rounded-xl bg-bg-surface border border-bg-border animate-pulse" />
          ))}
        </div>
      ) : prove ? (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <StatCard
              label="Confirmed Catches"
              value={prove.confirmed_catches}
              sub="actual interventions"
              color="success"
              icon={<ShieldCheck size={14} />}
            />
            <StatCard
              label="Accuracy"
              value={`${(prove.intervention_accuracy * 100).toFixed(1)}%`}
              sub="intervention quality"
              color={prove.intervention_accuracy >= 0.7 ? "success" : "warning"}
              icon={<Target size={14} />}
            />
            <StatCard
              label="False Negatives"
              value={prove.false_negatives}
              sub="missed issues"
              color={prove.false_negatives === 0 ? "success" : "danger"}
              icon={<XCircle size={14} />}
            />
            <StatCard
              label="Safe Passes"
              value={prove.safe_passes}
              sub="correct proceed"
              color="accent"
              icon={<CheckCircle size={14} />}
            />
            <StatCard
              label="Policy Enforcements"
              value={prove.total_policy_enforcements}
              sub="org policy hits"
              color="accent"
              icon={<AlertTriangle size={14} />}
            />
          </div>

          {/* Verdict */}
          {prove.verdict && <VerdictCard verdict={prove.verdict} />}

          {/* Score Trajectory */}
          {trajectory.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle icon={<TrendingUp size={14} />}>Score Trajectory</CardTitle>
              </CardHeader>
              <CardBody>
                <ScoreTimeline data={trajectory} height={200} color="#22c55e" />
              </CardBody>
            </Card>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Top Catches */}
            <Card>
              <CardHeader>
                <CardTitle icon={<ShieldCheck size={14} />}>Top Interventions</CardTitle>
                <Badge variant="success">{prove.top_catches.length} confirmed</Badge>
              </CardHeader>
              <div className="divide-y divide-bg-border/50 max-h-80 overflow-y-auto">
                {prove.top_catches.map((c, i) => (
                  <div key={i} className="px-5 py-3">
                    <div className="flex items-center gap-2 mb-1">
                      <ActionBadge action={c.decision} />
                      {c.policy_name && (
                        <Badge variant="accent" size="sm">{c.policy_name}</Badge>
                      )}
                      <span className="text-[10px] text-muted ml-auto">{formatTime(c.timestamp)}</span>
                    </div>
                    <p className="text-xs text-white/80 truncate">{c.task}</p>
                    <p className="text-[10px] text-muted mt-0.5">{c.reason}</p>
                  </div>
                ))}
                {!prove.top_catches.length && (
                  <div className="px-5 py-8 text-xs text-muted text-center">
                    No confirmed catches yet — record outcomes to build this report.
                  </div>
                )}
              </div>
            </Card>

            {/* Policy Stats */}
            <Card>
              <CardHeader>
                <CardTitle icon={<AlertTriangle size={14} />}>Policy Enforcement</CardTitle>
              </CardHeader>
              <div className="divide-y divide-bg-border/50">
                {prove.policy_stats.map((p) => (
                  <div key={p.policy_name} className="px-5 py-3 flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-mono text-white/80 truncate">{p.policy_name}</div>
                      <ActionBadge action={p.enforce_action} />
                    </div>
                    <SeverityBadge severity={p.severity} />
                    <div className="text-right">
                      <div className="text-sm font-bold text-white">{p.trigger_count}</div>
                      <div className="text-[10px] text-muted">triggers</div>
                    </div>
                  </div>
                ))}
                {!prove.policy_stats.length && (
                  <div className="px-5 py-8 text-xs text-muted text-center">
                    No policy enforcements recorded
                  </div>
                )}
              </div>
            </Card>
          </div>

          {/* Agent Compliance Table */}
          {prove.agent_compliance.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Agent Compliance</CardTitle>
              </CardHeader>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-bg-border">
                      {["Agent", "Judgment Score", "Episodes", "Policy Hits"].map((h) => (
                        <th key={h} className="px-4 py-2.5 text-left text-muted font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {prove.agent_compliance.map((a) => (
                      <tr key={a.agent_id} className="border-b border-bg-border/50 hover:bg-bg-hover transition-colors">
                        <td className="px-4 py-2.5 font-mono text-accent-light">{a.agent_id}</td>
                        <td className="px-4 py-2.5">
                          <Badge
                            variant={a.score >= 0.75 ? "success" : a.score >= 0.5 ? "warning" : "danger"}
                          >
                            {(a.score * 100).toFixed(0)}%
                          </Badge>
                        </td>
                        <td className="px-4 py-2.5 text-white/80">{a.total_episodes}</td>
                        <td className="px-4 py-2.5">
                          {a.policy_hits > 0
                            ? <Badge variant="warning">{a.policy_hits}</Badge>
                            : <span className="text-muted">0</span>
                          }
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      ) : (
        <div className="text-center py-16 text-xs text-muted">
          No proof of value data available yet
        </div>
      )}
    </div>
  );
}
