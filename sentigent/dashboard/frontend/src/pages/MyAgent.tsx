/**
 * My Agent — user's personal Layer 1 view from Supabase.
 * Shows synced episodes for their claimed agent_id.
 * Focus: human ↔ agent interaction, self-learning progress.
 */
import { useState, useEffect } from "react";
import {
  Bot, Brain, TrendingUp, Loader2, AlertCircle,
  ChevronDown, ChevronUp, CheckCircle,
  Zap,
} from "lucide-react";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/context/AuthContext";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/Card";
import { ActionBadge, OutcomeBadge } from "@/components/ui/Badge";
import { ScoreRing } from "@/components/ui/ScoreRing";

interface SyncedEpisode {
  id: number;
  agent_id: string;
  trace_id: string;
  task: string;
  decision: string;
  reason: string;
  confidence_at_decision: number;
  outcome: string | null;
  created_at: string;
  signals: Record<string, number>;
}

interface AgentScore {
  total: number;
  correct: number;
  score: number;
}

export function MyAgent() {
  const { membership } = useAuth();
  const [agentId, setAgentId] = useState<string>("");
  const [agentIds, setAgentIds] = useState<string[]>([]);
  const [episodes, setEpisodes] = useState<SyncedEpisode[]>([]);
  const [score, setScore] = useState<AgentScore | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // Load available agent_ids for this org
  useEffect(() => {
    if (!membership?.org_id) return;
    supabase
      .from("synced_episodes")
      .select("agent_id")
      .eq("org_id", membership.org_id)
      .order("created_at", { ascending: false })
      .limit(500)
      .then(({ data }) => {
        if (!data) return;
        const unique = [...new Set(data.map(r => r.agent_id))];
        setAgentIds(unique);
        if (unique.length > 0 && !agentId) setAgentId(unique[0]);
      });
  }, [membership?.org_id]);

  // Load episodes for selected agent
  useEffect(() => {
    if (!agentId || !membership?.org_id) return;
    setLoading(true);
    setError(null);

    supabase
      .from("synced_episodes")
      .select("id,agent_id,trace_id,task,decision,reason,confidence_at_decision,outcome,created_at,signals")
      .eq("org_id", membership.org_id)
      .eq("agent_id", agentId)
      .order("created_at", { ascending: false })
      .limit(100)
      .then(({ data, error: err }) => {
        setLoading(false);
        if (err) { setError(err.message); return; }
        const rows = (data ?? []) as SyncedEpisode[];
        setEpisodes(rows);

        // Compute score
        const rated = rows.filter(r => r.outcome !== null);
        const correct = rated.filter(r => r.outcome === "correct").length;
        setScore({
          total: rows.length,
          correct,
          score: rated.length > 0 ? correct / rated.length : 0,
        });
      });
  }, [agentId, membership?.org_id]);

  const scorePct = Math.round((score?.score ?? 0) * 100);

  return (
    <div className="p-6 space-y-5 max-w-4xl">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Bot size={18} className="text-accent-light" />
            My Agent
          </h2>
          <p className="text-sm text-muted/60 mt-0.5">
            Your agent's decisions synced from Layer 1 to your org cloud
          </p>
        </div>

        {agentIds.length > 0 && (
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted/60">Agent:</label>
            <select
              value={agentId}
              onChange={e => setAgentId(e.target.value)}
              className="input text-xs py-1.5 px-2.5 h-8 min-w-[160px]"
            >
              {agentIds.map(id => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Score summary */}
      {score && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-xl border border-bg-border/60 p-4 flex flex-col items-center gap-2"
            style={{ background: "linear-gradient(135deg, rgba(124,58,237,0.08), rgba(124,58,237,0.03))" }}>
            <ScoreRing score={scorePct} size={56} strokeWidth={5} />
            <p className="text-[11px] text-muted/60 text-center">Judgment Score</p>
          </div>
          {[
            { label: "Total Decisions", value: score.total, icon: <Brain size={14} className="text-accent-light" /> },
            { label: "Correct", value: score.correct, icon: <CheckCircle size={14} className="text-success" /> },
            { label: "Improvement", value: scorePct >= 75 ? "On Track" : "Learning", icon: <TrendingUp size={14} className="text-amber-400" /> },
          ].map(({ label, value, icon }) => (
            <div key={label} className="rounded-xl border border-bg-border/60 p-4"
              style={{ background: "rgba(255,255,255,0.02)" }}>
              <div className="flex items-center gap-1.5 mb-1">{icon}<span className="text-[10px] text-muted/60">{label}</span></div>
              <p className="text-xl font-bold text-white tabular">{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Episodes */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Zap size={14} />}>
            Recent Decisions {episodes.length > 0 && <span className="text-muted/50 font-normal text-xs ml-1">({episodes.length})</span>}
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
          {!loading && !error && episodes.length === 0 && (
            <div className="py-10 text-center">
              <Bot size={28} className="text-muted/30 mx-auto mb-3" />
              <p className="text-sm text-muted/50">No episodes synced yet</p>
              <p className="text-xs text-muted/40 mt-1">
                Set <code className="text-accent-light/60">SENTIGENT_ORG_ID</code> in your agent's .env and run a task
              </p>
            </div>
          )}
          {episodes.map(ep => {
            const expanded = expandedId === ep.id;
            const confidencePct = Math.round((ep.confidence_at_decision ?? 0) * 100);
            return (
              <div key={ep.id} className="border-b border-bg-border/40 last:border-0">
                <button
                  className="w-full flex items-center gap-3 px-4 py-3 hover:bg-bg-hover/30 transition-colors text-left"
                  onClick={() => setExpandedId(expanded ? null : ep.id)}
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white/90 truncate">{ep.task}</p>
                    <p className="text-[11px] text-muted/50 mt-0.5">
                      {new Date(ep.created_at).toLocaleString()} · {ep.agent_id}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <ActionBadge action={ep.decision} />
                    <OutcomeBadge outcome={ep.outcome} />
                    <span className="text-[10px] text-muted/50 tabular w-8 text-right">{confidencePct}%</span>
                    {expanded ? <ChevronUp size={13} className="text-muted/40" /> : <ChevronDown size={13} className="text-muted/40" />}
                  </div>
                </button>
                {expanded && (
                  <div className="px-4 pb-4 pt-1 bg-bg-base/50 border-t border-bg-border/30">
                    <p className="text-xs text-muted/80 leading-relaxed mb-3">{ep.reason}</p>
                    {Object.keys(ep.signals ?? {}).length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(ep.signals).map(([k, v]) => (
                          <span key={k} className="text-[10px] px-2 py-0.5 rounded-full border border-bg-border/60 text-muted/60 font-mono">
                            {k}: {typeof v === "number" ? v.toFixed(2) : v}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </CardBody>
      </Card>
    </div>
  );
}
