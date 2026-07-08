/**
 * Admin Layer 1 — org admin sees ALL agents' synced episodes.
 * Compare judgment scores across agents, identify outliers.
 */
import { useState, useEffect } from "react";
import {
  Shield, Bot, TrendingUp, TrendingDown, Minus as MinusIcon,
  Loader2, AlertCircle, ChevronRight,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/context/AuthContext";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ScoreRing } from "@/components/ui/ScoreRing";

interface AgentSummary {
  agent_id: string;
  total: number;
  correct: number;
  incorrect: number;
  neutral: number;
  score: number;
  last_decision: string;
}

export function AdminLayer1() {
  const { membership } = useAuth();
  const navigate = useNavigate();
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const isAdmin = membership?.role === "owner" || membership?.role === "admin";

  useEffect(() => {
    if (!membership?.org_id) return;
    setLoading(true);

    supabase
      .from("synced_episodes")
      .select("agent_id,outcome,created_at")
      .eq("org_id", membership.org_id)
      .order("created_at", { ascending: false })
      .limit(5000)
      .then(({ data, error: err }) => {
        setLoading(false);
        if (err) { setError(err.message); return; }

        // Aggregate per agent_id
        const map = new Map<string, AgentSummary>();
        for (const row of data ?? []) {
          const a = map.get(row.agent_id) ?? {
            agent_id: row.agent_id,
            total: 0, correct: 0, incorrect: 0, neutral: 0,
            score: 0, last_decision: row.created_at,
          };
          a.total++;
          if (row.outcome === "correct") a.correct++;
          else if (row.outcome === "incorrect") a.incorrect++;
          else if (row.outcome === "neutral") a.neutral++;
          if (row.created_at > a.last_decision) a.last_decision = row.created_at;
          map.set(row.agent_id, a);
        }

        // Compute score and sort by total desc
        const summaries = Array.from(map.values()).map(a => {
          const rated = a.correct + a.incorrect;
          return { ...a, score: rated > 0 ? a.correct / rated : 0 };
        }).sort((x, y) => y.total - x.total);

        setAgents(summaries);
      });
  }, [membership?.org_id]);

  if (!isAdmin) {
    return (
      <div className="p-6 max-w-xl">
        <div className="rounded-xl border border-danger/30 bg-danger/10 p-6 text-center">
          <Shield size={28} className="text-danger mx-auto mb-3" />
          <p className="text-sm font-semibold text-white mb-1">Admin access required</p>
          <p className="text-xs text-muted/60">Only admins and owners can view all agents' Layer 1 data.</p>
        </div>
      </div>
    );
  }

  const avgScore = agents.length > 0
    ? agents.reduce((sum, a) => sum + a.score, 0) / agents.length
    : 0;

  return (
    <div className="p-6 space-y-5 max-w-4xl">
      <div>
        <h2 className="text-lg font-bold text-white flex items-center gap-2">
          <Shield size={18} className="text-accent-light" />
          Admin — All Agents Layer 1
        </h2>
        <p className="text-sm text-muted/60 mt-0.5">
          Cross-agent judgment health for <span className="text-accent-light/80">{membership?.org_name}</span>
        </p>
      </div>

      {/* Org-level summary */}
      {agents.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-bg-border/60 p-4 flex flex-col items-center gap-2"
            style={{ background: "linear-gradient(135deg, rgba(124,58,237,0.08), rgba(124,58,237,0.03))" }}>
            <ScoreRing score={Math.round(avgScore * 100)} size={52} strokeWidth={5} />
            <p className="text-[11px] text-muted/60">Org Avg Score</p>
          </div>
          <div className="rounded-xl border border-bg-border/60 p-4"
            style={{ background: "rgba(255,255,255,0.02)" }}>
            <p className="text-[10px] text-muted/60 mb-1">Active Agents</p>
            <p className="text-2xl font-bold text-white tabular">{agents.length}</p>
          </div>
          <div className="rounded-xl border border-bg-border/60 p-4"
            style={{ background: "rgba(255,255,255,0.02)" }}>
            <p className="text-[10px] text-muted/60 mb-1">Total Decisions</p>
            <p className="text-2xl font-bold text-white tabular">
              {agents.reduce((s, a) => s + a.total, 0).toLocaleString()}
            </p>
          </div>
        </div>
      )}

      {/* Agents table */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Bot size={14} />}>
            Agents ({agents.length})
          </CardTitle>
        </CardHeader>
        <CardBody className="p-0">
          {loading && (
            <div className="flex items-center justify-center py-10">
              <Loader2 size={20} className="animate-spin text-accent-light/60" />
            </div>
          )}
          {error && (
            <div className="flex items-center gap-2 px-5 py-4 text-danger text-sm">
              <AlertCircle size={15} /> {error}
            </div>
          )}
          {!loading && !error && agents.length === 0 && (
            <div className="py-10 text-center">
              <Bot size={28} className="text-muted/30 mx-auto mb-3" />
              <p className="text-sm text-muted/50">No agents have synced data yet</p>
            </div>
          )}

          {/* Header row */}
          {agents.length > 0 && (
            <div className="grid grid-cols-[1fr_80px_80px_80px_90px_40px] gap-3 px-4 py-2 border-b border-bg-border/40 text-[10px] text-muted/50 uppercase tracking-wider">
              <span>Agent</span>
              <span className="text-center">Score</span>
              <span className="text-center">Total</span>
              <span className="text-center">Correct</span>
              <span>Last Active</span>
              <span />
            </div>
          )}

          {agents.map(agent => {
            const pct = Math.round(agent.score * 100);
            const scoreColor = pct >= 80 ? "success" : pct >= 60 ? "warning" : "danger";
            const trend = pct >= 80
              ? <TrendingUp size={12} className="text-success" />
              : pct >= 60
                ? <MinusIcon size={12} className="text-warning" />
                : <TrendingDown size={12} className="text-danger" />;

            return (
              <div
                key={agent.agent_id}
                className="grid grid-cols-[1fr_80px_80px_80px_90px_40px] gap-3 items-center px-4 py-3 border-b border-bg-border/40 last:border-0 hover:bg-bg-hover/20 cursor-pointer group"
                onClick={() => navigate(`/agents?agent=${encodeURIComponent(agent.agent_id)}`)}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center flex-shrink-0">
                    <Bot size={12} className="text-accent-light" />
                  </div>
                  <span className="text-sm text-white/90 font-mono truncate">{agent.agent_id}</span>
                </div>
                <div className="text-center">
                  <Badge variant={scoreColor} dot>{pct}%</Badge>
                </div>
                <div className="text-center">
                  <span className="text-sm tabular text-white/80">{agent.total}</span>
                </div>
                <div className="flex items-center justify-center gap-1">
                  {trend}
                  <span className="text-sm tabular text-white/80">{agent.correct}</span>
                </div>
                <div>
                  <span className="text-[11px] text-muted/50">
                    {new Date(agent.last_decision).toLocaleDateString()}
                  </span>
                </div>
                <ChevronRight size={13} className="text-muted/30 group-hover:text-accent-light transition-colors" />
              </div>
            );
          })}
        </CardBody>
      </Card>
    </div>
  );
}
