import { useState } from "react";
import {
  LayoutDashboard, TrendingUp, Users, Brain, Search,
  AlertTriangle, CheckCircle2, Activity, Layers, FlaskConical,
} from "lucide-react";
import { useScore, useTimeline, useInsights, useEpisodes, useLayer2Org, useLayer2Status, useSprint } from "@/api/hooks";
import { Card, CardHeader, CardTitle, CardBody, StatCard, Badge, ActionBadge, OutcomeBadge } from "@/components/ui";
import { SkeletonCard, SkeletonTable } from "@/components/ui/Skeleton";
import { ScoreTimeline } from "@/components/charts/ScoreTimeline";
import { SignalBars } from "@/components/charts/SignalBars";
import { ScoreRing } from "@/components/ui/ScoreRing";

function formatTime(ts: string) {
  return new Date(ts).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

function truncate(s: string, n = 55) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

export function Dashboard() {
  const [search, setSearch] = useState("");
  const { data: score, isLoading: scoreLoading } = useScore();
  const { data: timeline } = useTimeline();
  const { data: insights } = useInsights();
  const { data: episodes, isLoading: epLoading } = useEpisodes(30, search);
  const { data: l2Status } = useLayer2Status();
  const { data: orgData } = useLayer2Org();
  const { data: sprint } = useSprint();

  const isOrgConfigured = l2Status?.configured;

  return (
    <div className="p-6 space-y-5">
      {/* Hero: Score + Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {scoreLoading ? (
          Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)
        ) : score ? (
          <>
            {/* Score ring card */}
            <div
              className="sm:col-span-2 lg:col-span-1 rounded-xl p-5 flex items-center gap-5 relative overflow-hidden border"
              style={{
                background: "linear-gradient(135deg, rgba(124,58,237,0.12) 0%, rgba(124,58,237,0.04) 100%)",
                borderColor: "rgba(124,58,237,0.25)",
              }}
            >
              <div className="absolute top-0 right-0 w-24 h-24 pointer-events-none"
                style={{ background: "radial-gradient(circle at 80% 20%, rgba(124,58,237,0.12) 0%, transparent 70%)" }} />
              <ScoreRing score={score.score} size={76} label="Judgment Score" showGlow />
              <div className="relative">
                <div className="text-[10px] font-semibold text-muted uppercase tracking-widest mb-1.5">
                  Layer 1 Score
                </div>
                <div className="text-3xl font-bold text-gradient leading-none mb-1 tabular">
                  {score.score_pct}
                </div>
                <div className="text-xs text-muted tabular">{score.total_episodes} total episodes</div>
              </div>
            </div>

            <StatCard
              label="Correct Calls"
              value={score.outcomes.correct}
              sub={`of ${score.total_with_outcomes} rated`}
              color="success"
              icon={<CheckCircle2 size={14} />}
            />
            <StatCard
              label="Incorrect Calls"
              value={score.outcomes.incorrect}
              color={score.outcomes.incorrect > 5 ? "danger" : "default"}
              sub={score.total_with_outcomes > 0
                ? `${((score.outcomes.incorrect / score.total_with_outcomes) * 100).toFixed(0)}% error rate`
                : "no rated episodes"}
              icon={<AlertTriangle size={14} />}
            />
            <StatCard
              label="Agents in Org"
              value={isOrgConfigured ? (orgData?.total_agents ?? "—") : "—"}
              sub={isOrgConfigured ? "Layer 2 active" : "Configure Layer 2"}
              color="accent"
              icon={<Users size={14} />}
            />
          </>
        ) : null}
      </div>

      {/* Truth Sprint — WS-B ablation harness */}
      {sprint && (
        <Card>
          <CardHeader>
            <CardTitle icon={<FlaskConical size={13} />}>
              Truth Sprint — SWE-bench ablation
            </CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant={sprint.assumptions_passed === sprint.assumptions_total ? "success" : "warning"}>
                {sprint.assumptions_passed}/{sprint.assumptions_total} assumptions
              </Badge>
              <Badge variant="success">${sprint.metered_cost_usd.toFixed(0)} metered</Badge>
            </div>
          </CardHeader>
          <CardBody>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {/* Harness status */}
              <div>
                <div className="text-[10px] font-semibold text-muted uppercase tracking-widest mb-2">
                  WS-B harness
                </div>
                <div className="flex items-center gap-1.5 mb-2">
                  <CheckCircle2 size={14} className="text-success" />
                  <span className="text-sm font-semibold text-white capitalize">{sprint.wsb_status}</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {sprint.wsb_slices.map((s) => (
                    <Badge key={s} variant="default">{s}</Badge>
                  ))}
                </div>
              </div>

              {/* Ablation arms — VACR per arm */}
              <div>
                <div className="text-[10px] font-semibold text-muted uppercase tracking-widest mb-2">
                  Ablation VACR
                </div>
                <div className="space-y-1.5">
                  {(["a0", "a1", "a2"] as const).map((arm) => {
                    const a = sprint.ablation[arm];
                    return (
                      <div key={arm} className="flex items-center justify-between text-sm">
                        <span className="text-muted uppercase tabular">{arm}</span>
                        <span className="tabular text-white">
                          {a && a.vacr !== null ? `${(a.vacr * 100).toFixed(0)}% (n=${a.n})` : "—"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Verdict */}
              <div>
                <div className="text-[10px] font-semibold text-muted uppercase tracking-widest mb-2">
                  Verdict
                </div>
                <div className="text-sm text-white leading-snug">{sprint.verdict}</div>
                {!sprint.has_real_pilot && (
                  <div className="text-xs text-muted mt-2">
                    Pilot not yet run — see docs/WSB-REAL-FINDINGS.md
                  </div>
                )}
              </div>
            </div>
          </CardBody>
        </Card>
      )}

      {/* Timeline + Insights */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle icon={<TrendingUp size={13} />}>Score Timeline (30 days)</CardTitle>
            {insights?.brier_score != null && (
              <Badge
                variant={insights.brier_score < 0.15 ? "success" : insights.brier_score < 0.25 ? "warning" : "danger"}
              >
                Brier {insights.brier_score.toFixed(3)}
              </Badge>
            )}
          </CardHeader>
          <CardBody className="pt-2">
            <ScoreTimeline data={timeline ?? []} height={160} />
          </CardBody>
        </Card>

        {/* Insights panel */}
        <Card>
          <CardHeader>
            <CardTitle icon={<Brain size={13} />}>AI Insights</CardTitle>
            {insights && (
              <span className="text-[10px] text-muted">
                {[...insights.correlations, ...insights.trends, ...insights.anomalies].length} found
              </span>
            )}
          </CardHeader>
          <div className="divide-y divide-bg-border/40 max-h-[240px] overflow-y-auto">
            {!insights || (!insights.correlations.length && !insights.trends.length && !insights.anomalies.length) ? (
              <div className="px-5 py-8 text-center">
                <Activity size={24} className="text-muted/40 mx-auto mb-2" />
                <p className="text-xs text-muted">No insights yet — keep evaluating actions to build data.</p>
              </div>
            ) : (
              [...insights.correlations, ...insights.trends, ...insights.anomalies]
                .slice(0, 6)
                .map((ins, i) => (
                  <div key={i} className="px-4 py-3 hover:bg-bg-elevated/40 transition-colors">
                    <div className="flex items-center gap-1.5 mb-1">
                      <Badge
                        variant={
                          ins.category === "anomaly" ? "danger"
                            : ins.category === "trend" ? "info"
                            : "accent"
                        }
                        size="sm"
                      >
                        {ins.category}
                      </Badge>
                      <span className="text-[10px] text-muted ml-auto">
                        {(ins.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <p className="text-xs text-white/80 leading-relaxed">{ins.finding}</p>
                  </div>
                ))
            )}
          </div>
        </Card>
      </div>

      {/* Org agents table */}
      {isOrgConfigured && orgData && orgData.agents.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle icon={<Layers size={13} />}>Org Agent Health</CardTitle>
            <Badge variant="accent" dot>{orgData.total_agents} agents</Badge>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-bg-border"
                  style={{ background: "rgba(20,27,38,0.4)" }}>
                  {["Agent ID", "Episodes", "Score", "Correct", "Incorrect"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left text-muted font-semibold tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orgData.agents.map((a) => (
                  <tr key={a.agent_id} className="border-b border-bg-border/40 hover:bg-bg-hover transition-colors">
                    <td className="px-4 py-3 font-mono text-accent-light text-[11px]">{a.agent_id}</td>
                    <td className="px-4 py-3 text-white/70 tabular">{a.total_episodes}</td>
                    <td className="px-4 py-3">
                      <Badge variant={a.score >= 0.75 ? "success" : a.score >= 0.5 ? "warning" : "danger"}>
                        {a.score_pct}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-success-light tabular font-medium">{a.correct}</td>
                    <td className="px-4 py-3 text-danger-light tabular font-medium">{a.incorrect}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Recent Decisions */}
      <Card>
        <CardHeader>
          <CardTitle icon={<LayoutDashboard size={13} />}>Recent Decisions</CardTitle>
          <div className="relative">
            <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
            <input
              type="text"
              placeholder="Filter by task…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="input pl-7 w-44"
            />
          </div>
        </CardHeader>

        {epLoading ? (
          <SkeletonTable rows={6} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-bg-border"
                  style={{ background: "rgba(20,27,38,0.4)" }}>
                  {["Task", "Decision", "Outcome", "Confidence", "Signals", "Time"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left text-muted font-semibold tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(episodes ?? []).map((ep) => (
                  <tr key={ep.trace_id} className="border-b border-bg-border/40 hover:bg-bg-hover transition-colors group">
                    <td className="px-4 py-3 text-white/80 max-w-xs" title={ep.task}>
                      <span className="truncate block max-w-[280px]">{truncate(ep.task)}</span>
                    </td>
                    <td className="px-4 py-3"><ActionBadge action={ep.decision} /></td>
                    <td className="px-4 py-3"><OutcomeBadge outcome={ep.outcome} /></td>
                    <td className="px-4 py-3 text-white/60 tabular font-medium">
                      {(ep.confidence_at_decision * 100).toFixed(0)}%
                    </td>
                    <td className="px-4 py-3"><SignalBars signals={ep.signals} compact /></td>
                    <td className="px-4 py-3 text-muted font-mono text-[11px]">{formatTime(ep.timestamp)}</td>
                  </tr>
                ))}
                {!episodes?.length && (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-muted">
                      No decisions yet — start using Sentigent to see data here.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
