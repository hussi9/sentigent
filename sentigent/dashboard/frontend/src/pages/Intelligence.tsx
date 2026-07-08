/**
 * Intelligence Hub — the central AI intelligence layer.
 *
 * Shows the live network of connected agents, collective learning activity,
 * peer patterns, cross-agent insights, and real-time signal stream.
 *
 * This is the moat: more agents connected = better intelligence for all.
 */
import { useState, useEffect, useCallback } from "react";
import {
  Brain, Network, Zap, TrendingUp, RefreshCw,
  Activity, ChevronDown, ChevronUp, Bot, Loader2, AlertCircle,
  Cpu, Share2, Sparkles,
} from "lucide-react";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/Card";
import { ScoreRing } from "@/components/ui/ScoreRing";

const API = "/api/intelligence";

interface HubStatus {
  running: boolean;
  org_id: string;
  connected_agents: number;
  total_signals_processed: number;
  last_learn_cycle: number | null;
  learner_report: {
    agents_analyzed: number;
    threshold_updates: number;
    policies_generated: number;
    insights: string[];
    regression_detected: boolean;
  } | null;
}

interface AgentNode {
  agent_id: string;
  connected_at: number;
  last_heartbeat: number;
  judgment_score: number;
  decision_count: number;
  is_alive: boolean;
  capabilities: string[];
}

interface Pattern {
  pattern_name: string;
  learned_action: string;
  success_rate: number;
  sample_size: number;
  contributing_agents: string[];
  last_reinforced: string;
}

interface Signal {
  signal_type: string;
  agent_id: string;
  payload: Record<string, unknown>;
  timestamp: number;
}

const ACTION_COLORS: Record<string, string> = {
  proceed:    "text-emerald-400 bg-emerald-400/10 border-emerald-400/30",
  enrich:     "text-blue-400 bg-blue-400/10 border-blue-400/30",
  slow_down:  "text-amber-400 bg-amber-400/10 border-amber-400/30",
  escalate:   "text-red-400 bg-red-400/10 border-red-400/30",
};

const SIGNAL_COLORS: Record<string, string> = {
  decision:   "text-violet-400",
  outcome:    "text-emerald-400",
  prompt:     "text-blue-400",
  heartbeat:  "text-muted/40",
  pattern:    "text-amber-400",
};

export function Intelligence() {
  const [status, setStatus] = useState<HubStatus | null>(null);
  const [agents, setAgents] = useState<AgentNode[]>([]);
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [learning, setLearning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [statusRes, networkRes, patternsRes, signalsRes] = await Promise.all([
        fetch(`${API}/status`),
        fetch(`${API}/network`),
        fetch(`${API}/patterns`),
        fetch(`${API}/signals?limit=30`),
      ]);
      const [s, n, p, sig] = await Promise.all([
        statusRes.json(), networkRes.json(), patternsRes.json(), signalsRes.json(),
      ]);
      setStatus(s);
      setAgents(n.agents || []);
      setPatterns(p.patterns || []);
      setSignals(sig.signals || []);
      setError(null);
    } catch (e) {
      setError("Failed to load intelligence hub");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 10_000); // refresh every 10s
    return () => clearInterval(interval);
  }, [load]);

  const triggerLearn = async () => {
    setLearning(true);
    try {
      const res = await fetch(`${API}/learn`, { method: "POST" });
      const data = await res.json();
      if (data.status === "ok") await load();
    } catch {/* ignore */} finally {
      setLearning(false);
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center h-48">
      <Loader2 size={22} className="animate-spin text-accent-light/60" />
    </div>
  );

  const aliveCount = agents.filter(a => a.is_alive).length;
  const avgScore = agents.length > 0
    ? Math.round(agents.reduce((s, a) => s + (a.judgment_score ?? 0), 0) / agents.length * 100)
    : 0;

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Brain size={18} className="text-accent-light" />
            Intelligence Hub
          </h2>
          <p className="text-sm text-muted/60 mt-0.5">
            Central AI layer — connects agents, reads signals, learns collectively
          </p>
        </div>
        <button
          onClick={triggerLearn}
          disabled={learning}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-accent-light/30
            text-accent-light text-xs hover:bg-accent-light/10 transition-colors disabled:opacity-50"
        >
          {learning
            ? <Loader2 size={12} className="animate-spin" />
            : <RefreshCw size={12} />}
          Learn Now
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-danger text-sm">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Key metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {/* Hub running indicator */}
        <div className="rounded-xl border border-bg-border/60 p-4"
          style={{ background: "linear-gradient(135deg, rgba(124,58,237,0.08), rgba(124,58,237,0.03))" }}>
          <div className="flex items-center gap-1.5 mb-2">
            <div className={`w-2 h-2 rounded-full ${status?.running ? "bg-emerald-400 animate-pulse" : "bg-muted/30"}`} />
            <span className="text-[10px] text-muted/60">Hub Status</span>
          </div>
          <p className="text-sm font-bold text-white">
            {status?.running ? "Active" : "Offline"}
          </p>
          <p className="text-[10px] text-muted/50 mt-0.5">
            {status?.total_signals_processed?.toLocaleString() ?? 0} signals
          </p>
        </div>

        {/* Connected agents */}
        <div className="rounded-xl border border-bg-border/60 p-4" style={{ background: "rgba(255,255,255,0.02)" }}>
          <div className="flex items-center gap-1.5 mb-2">
            <Network size={12} className="text-accent-light" />
            <span className="text-[10px] text-muted/60">Connected Agents</span>
          </div>
          <p className="text-2xl font-bold text-white tabular">{aliveCount}</p>
          <p className="text-[10px] text-muted/50 mt-0.5">{agents.length} total registered</p>
        </div>

        {/* Collective score */}
        <div className="rounded-xl border border-bg-border/60 p-4 flex flex-col items-center gap-1"
          style={{ background: "rgba(255,255,255,0.02)" }}>
          <ScoreRing score={avgScore} size={44} strokeWidth={4} />
          <p className="text-[10px] text-muted/60">Collective Score</p>
        </div>

        {/* Patterns learned */}
        <div className="rounded-xl border border-bg-border/60 p-4" style={{ background: "rgba(255,255,255,0.02)" }}>
          <div className="flex items-center gap-1.5 mb-2">
            <Sparkles size={12} className="text-amber-400" />
            <span className="text-[10px] text-muted/60">Peer Patterns</span>
          </div>
          <p className="text-2xl font-bold text-white tabular">{patterns.length}</p>
          <p className="text-[10px] text-muted/50 mt-0.5">shared across agents</p>
        </div>
      </div>

      {/* Learner insights */}
      {status?.learner_report?.insights && status.learner_report.insights.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle icon={<Brain size={13} />}>
              Cross-Agent Insights
              {status.learner_report.regression_detected && (
                <span className="ml-2 text-[10px] text-red-400 border border-red-400/30 rounded px-1.5 py-0.5">
                  Regression Detected
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardBody>
            <div className="space-y-1.5">
              {status.learner_report.insights.map((insight, i) => (
                <div key={i} className="flex items-start gap-2 text-xs text-muted/70">
                  <TrendingUp size={11} className="text-accent-light mt-0.5 flex-shrink-0" />
                  {insight}
                </div>
              ))}
              <div className="flex gap-4 pt-2 text-[10px] text-muted/50 border-t border-bg-border/40 mt-2">
                <span>Agents analyzed: {status.learner_report.agents_analyzed}</span>
                <span>Threshold updates: {status.learner_report.threshold_updates}</span>
                <span>Auto-policies: {status.learner_report.policies_generated}</span>
              </div>
            </div>
          </CardBody>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Agent Network */}
        <Card>
          <CardHeader>
            <CardTitle icon={<Network size={13} />}>
              Agent Network
              <span className="text-muted/50 font-normal text-xs ml-1">({agents.length})</span>
            </CardTitle>
          </CardHeader>
          <CardBody className="p-0">
            {agents.length === 0 ? (
              <div className="py-8 text-center">
                <Share2 size={24} className="text-muted/30 mx-auto mb-2" />
                <p className="text-sm text-muted/50">No agents connected yet</p>
                <p className="text-xs text-muted/40 mt-1">
                  Agents auto-register when Sentigent initializes
                </p>
              </div>
            ) : (
              agents.map(agent => {
                const expanded = expandedAgent === agent.agent_id;
                const scorePct = Math.round((agent.judgment_score ?? 0) * 100);
                return (
                  <div key={agent.agent_id} className="border-b border-bg-border/40 last:border-0">
                    <button
                      className="w-full flex items-center gap-3 px-4 py-3 hover:bg-bg-hover/20 text-left"
                      onClick={() => setExpandedAgent(expanded ? null : agent.agent_id)}
                    >
                      <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${agent.is_alive ? "bg-emerald-400" : "bg-muted/30"}`} />
                      <Bot size={13} className="text-accent-light flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-white/90 font-medium truncate">{agent.agent_id}</p>
                        <p className="text-[10px] text-muted/50">{agent.decision_count} decisions</p>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <div className="text-right">
                          <p className="text-xs font-bold text-white tabular">{scorePct}%</p>
                          <p className="text-[9px] text-muted/40">score</p>
                        </div>
                        {expanded ? <ChevronUp size={12} className="text-muted/40" /> : <ChevronDown size={12} className="text-muted/40" />}
                      </div>
                    </button>
                    {expanded && (
                      <div className="px-4 pb-3 pt-1 bg-bg-base/40 border-t border-bg-border/30">
                        <div className="flex flex-wrap gap-1.5">
                          {agent.capabilities.map(c => (
                            <span key={c} className="text-[10px] px-1.5 py-0.5 rounded border border-bg-border/60 text-muted/50 font-mono">
                              {c}
                            </span>
                          ))}
                        </div>
                        <p className="text-[10px] text-muted/40 mt-2">
                          Connected {new Date(agent.connected_at * 1000).toLocaleString()} ·{" "}
                          Last heartbeat {new Date(agent.last_heartbeat * 1000).toLocaleTimeString()}
                        </p>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </CardBody>
        </Card>

        {/* Peer Patterns */}
        <Card>
          <CardHeader>
            <CardTitle icon={<Sparkles size={13} />}>
              Peer Patterns
              <span className="text-muted/50 font-normal text-xs ml-1">({patterns.length})</span>
            </CardTitle>
          </CardHeader>
          <CardBody className="p-0">
            {patterns.length === 0 ? (
              <div className="py-8 text-center">
                <Cpu size={24} className="text-muted/30 mx-auto mb-2" />
                <p className="text-sm text-muted/50">No patterns yet</p>
                <p className="text-xs text-muted/40 mt-1">Patterns emerge after ~50 outcomes</p>
              </div>
            ) : (
              patterns.map((p, i) => {
                const successPct = Math.round(p.success_rate * 100);
                const colorClass = ACTION_COLORS[p.learned_action] || "text-muted/60 bg-muted/10 border-muted/20";
                return (
                  <div key={i} className="border-b border-bg-border/40 last:border-0 px-4 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-xs text-white/90 truncate font-medium">{p.pattern_name}</p>
                        <p className="text-[10px] text-muted/50 mt-0.5">
                          n={p.sample_size} · {p.contributing_agents?.length ?? 0} agents
                        </p>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${colorClass}`}>
                          {p.learned_action}
                        </span>
                        <span className="text-xs font-bold text-white tabular">{successPct}%</span>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </CardBody>
        </Card>
      </div>

      {/* Live Signal Stream */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Activity size={13} />}>
            Live Signal Stream
            <span className="text-muted/50 font-normal text-xs ml-1">
              (last {signals.length} signals — auto-refreshes)
            </span>
          </CardTitle>
        </CardHeader>
        <CardBody className="p-0">
          {signals.length === 0 ? (
            <div className="py-8 text-center">
              <Zap size={24} className="text-muted/30 mx-auto mb-2" />
              <p className="text-sm text-muted/50">No signals yet</p>
              <p className="text-xs text-muted/40 mt-1">Signals appear when agents evaluate decisions</p>
            </div>
          ) : (
            <div className="divide-y divide-bg-border/30">
              {signals
                .filter(s => s.signal_type !== "heartbeat")
                .slice(0, 20)
                .map((sig, i) => {
                  const colorClass = SIGNAL_COLORS[sig.signal_type] || "text-muted/50";
                  const action = sig.payload?.action as string | undefined;
                  const task = sig.payload?.task as string | undefined;
                  return (
                    <div key={i} className="px-4 py-2.5 flex items-center gap-3">
                      <span className={`text-[10px] font-mono uppercase tracking-wider ${colorClass} w-16 flex-shrink-0`}>
                        {sig.signal_type}
                      </span>
                      <span className="text-[10px] text-muted/50 w-24 truncate flex-shrink-0 font-mono">
                        {sig.agent_id}
                      </span>
                      <span className="text-xs text-white/70 truncate flex-1">
                        {task || JSON.stringify(sig.payload).slice(0, 80)}
                      </span>
                      {action && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded border flex-shrink-0 ${ACTION_COLORS[action] || "text-muted/50 border-muted/20"}`}>
                          {action}
                        </span>
                      )}
                      <span className="text-[10px] text-muted/30 flex-shrink-0">
                        {new Date(sig.timestamp * 1000).toLocaleTimeString()}
                      </span>
                    </div>
                  );
                })}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
