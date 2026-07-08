import { useState } from "react";
import { Bot, Search, TrendingUp, Zap } from "lucide-react";
import { useEpisodes, usePatterns, useBaselines, useScore, useTimeline } from "@/api/hooks";
import { Card, CardHeader, CardTitle, CardBody, StatCard, ActionBadge, OutcomeBadge, Badge } from "@/components/ui";
import { ScoreTimeline } from "@/components/charts/ScoreTimeline";
import { SignalBars } from "@/components/charts/SignalBars";
import { ScoreRing } from "@/components/ui/ScoreRing";

function formatTime(ts: string) {
  return new Date(ts).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function truncate(s: string, n = 80) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

export function AgentExplorer() {
  const [search, setSearch] = useState("");

  const { data: score } = useScore();
  const { data: timeline } = useTimeline();
  const { data: episodes } = useEpisodes(100, search);
  const { data: patterns } = usePatterns();
  const { data: baselines } = useBaselines();

  const filteredEpisodes = episodes ?? [];

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      {/* Agent Header */}
      <div className="flex items-center gap-4">
        <div className="flex-1">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <Bot size={16} className="text-accent-light" />
            Agent Explorer
          </h2>
          <p className="text-xs text-muted mt-0.5">
            Deep dive into individual agent judgment, patterns, and decision history
          </p>
        </div>
      </div>

      {/* Score Overview */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="col-span-2 lg:col-span-1 bg-bg-surface border border-bg-border rounded-xl p-5 flex items-center gap-5">
          <ScoreRing score={score?.score ?? 0} size={72} label="Current" />
          <div>
            <div className="text-xs text-muted uppercase tracking-wider mb-1">Judgment Score</div>
            <div className="text-2xl font-bold text-white">{score?.score_pct ?? "—"}</div>
            <div className="text-xs text-muted">{score?.total_episodes ?? 0} episodes total</div>
          </div>
        </div>
        <StatCard
          label="Patterns Learned"
          value={patterns?.length ?? 0}
          sub="procedural rules"
          icon={<Zap size={14} />}
          color="accent"
        />
        <StatCard
          label="Baselines"
          value={baselines?.length ?? 0}
          sub="metrics tracked"
          color="accent"
        />
        <StatCard
          label="Outcomes Rated"
          value={score?.total_with_outcomes ?? 0}
          sub={`of ${score?.total_episodes ?? 0}`}
          color={
            (score?.total_with_outcomes ?? 0) > 10 ? "success" : "warning"
          }
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Score Timeline */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle icon={<TrendingUp size={14} />}>Score History</CardTitle>
          </CardHeader>
          <CardBody>
            <ScoreTimeline data={timeline ?? []} height={200} />
          </CardBody>
        </Card>

        {/* Top Patterns */}
        <Card>
          <CardHeader>
            <CardTitle icon={<Zap size={14} />}>Learned Patterns</CardTitle>
          </CardHeader>
          <CardBody className="p-0">
            {!patterns?.length ? (
              <div className="px-5 py-8 text-xs text-muted text-center">
                No patterns learned yet
              </div>
            ) : (
              <div className="divide-y divide-bg-border/50">
                {patterns.slice(0, 8).map((p) => (
                  <div key={p.pattern_name} className="px-5 py-3 flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-mono text-white/80 truncate">{p.pattern_name}</div>
                      <div className="text-[10px] text-muted">{p.sample_size} samples</div>
                    </div>
                    <div className="text-right">
                      <ActionBadge action={p.learned_action} />
                      <div className="text-[10px] text-muted mt-0.5">{(p.success_rate * 100).toFixed(0)}%</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Decision History */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Bot size={14} />}>Decision History</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="muted">{filteredEpisodes.length} decisions</Badge>
            <div className="relative">
              <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="text"
                placeholder="Filter tasks…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-7 pr-3 py-1.5 text-xs bg-bg-elevated border border-bg-border rounded-md text-white placeholder-muted focus:outline-none focus:border-accent/50 w-48"
              />
            </div>
          </div>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-bg-border">
                {["Task", "Decision", "Outcome", "Confidence", "Signals", "Reason", "Time"].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-muted font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredEpisodes.map((ep) => (
                <tr
                  key={ep.trace_id}
                  className="border-b border-bg-border/50 hover:bg-bg-hover transition-colors cursor-pointer"
                >
                  <td className="px-4 py-2.5 max-w-xs">
                    <span className="text-white/80 truncate block" title={ep.task}>
                      {truncate(ep.task, 50)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5"><ActionBadge action={ep.decision} /></td>
                  <td className="px-4 py-2.5"><OutcomeBadge outcome={ep.outcome} /></td>
                  <td className="px-4 py-2.5">
                    <span className={`font-mono ${ep.confidence_at_decision >= 0.7 ? "text-success" : ep.confidence_at_decision >= 0.5 ? "text-warning" : "text-danger"}`}>
                      {(ep.confidence_at_decision * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="px-4 py-2.5"><SignalBars signals={ep.signals} compact /></td>
                  <td className="px-4 py-2.5 max-w-xs">
                    <span className="text-muted truncate block" title={ep.reason}>
                      {truncate(ep.reason ?? "", 40)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-muted font-mono whitespace-nowrap">
                    {formatTime(ep.timestamp)}
                  </td>
                </tr>
              ))}
              {!filteredEpisodes.length && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted">
                    No decisions found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Baselines */}
      {(baselines?.length ?? 0) > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Learned Baselines</CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-bg-border">
                  {["Metric", "Median", "Std Dev", "P5–P95 Range", "Samples", "Source"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left text-muted font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(baselines ?? []).map((b) => (
                  <tr key={b.metric} className="border-b border-bg-border/50 hover:bg-bg-hover transition-colors">
                    <td className="px-4 py-2.5 font-mono text-accent-light">{b.metric}</td>
                    <td className="px-4 py-2.5 text-white/80">{b.median.toFixed(3)}</td>
                    <td className="px-4 py-2.5 text-muted">{b.std.toFixed(3)}</td>
                    <td className="px-4 py-2.5 text-muted">[{b.p5.toFixed(2)}, {b.p95.toFixed(2)}]</td>
                    <td className="px-4 py-2.5 text-muted">{b.sample_size}</td>
                    <td className="px-4 py-2.5">
                      <Badge variant="muted" size="sm">{b.source}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
