import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  CheckCircle2, Circle, ChevronRight, Terminal, ShieldCheck,
  PlayCircle, TrendingUp, Zap, Copy, Check, BookOpen, Users,
  ArrowRight, Activity, Globe, Sparkles,
} from "lucide-react";
import { Card, CardBody } from "@/components/ui/Card";
import { useAuth } from "@/context/AuthContext";
import type { NavPage } from "@/types";

interface Step {
  id: string;
  title: string;
  role: "all" | "admin" | "developer";
  icon: React.ReactNode;
  description: string;
  content: React.ReactNode;
  estimatedMin: number;
}

function CodeBlock({ code, language = "bash" }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false);

  function copy() {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="relative rounded-xl overflow-hidden"
      style={{ background: "#070a10", border: "1px solid #1e293b" }}>
      <div className="flex items-center justify-between px-4 py-2 border-b border-bg-border/60"
        style={{ background: "rgba(20,27,38,0.7)" }}>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-danger/50" />
          <div className="w-2.5 h-2.5 rounded-full bg-warning/50" />
          <div className="w-2.5 h-2.5 rounded-full bg-success/50" />
          <span className="text-[10px] text-muted font-mono ml-2">{language}</span>
        </div>
        <button
          onClick={copy}
          className="flex items-center gap-1.5 text-[10px] transition-colors px-2 py-1 rounded-md hover:bg-bg-elevated"
          style={{ color: copied ? "#10b981" : "#475569" }}
        >
          {copied ? <Check size={10} /> : <Copy size={10} />}
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
      <pre className="p-4 text-xs font-mono text-accent-bright/90 overflow-x-auto leading-relaxed">{code}</pre>
    </div>
  );
}

function RoleBadge({ role }: { role: "all" | "admin" | "developer" }) {
  if (role === "all") return null;
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${
      role === "admin"
        ? "bg-danger/10 text-danger border-danger/20"
        : "bg-accent/10 text-accent-light border-accent/20"
    }`}>
      {role === "admin" ? "Admin only" : "Developer"}
    </span>
  );
}

function buildSteps(orgSlug: string, orgId: string, supabaseUrl: string): Step[] {
  return [
  {
    id: "what-is-sentigent",
    title: "What is Sentigent?",
    role: "all",
    icon: <Activity size={16} />,
    description: "Understand the 3-layer AI judgment architecture",
    estimatedMin: 3,
    content: (
      <div className="space-y-5">
        <p className="text-sm text-white/80 leading-relaxed">
          Sentigent is a <strong className="text-white">self-learning judgment layer</strong> that intercepts every
          Claude Code tool call, evaluates the risk, and learns from outcomes — so your agents get safer and smarter over time.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[
            {
              layer: "Layer 1", title: "Local Agent", color: "text-accent-light", bg: "bg-accent/10 border-accent/20",
              desc: "SQLite on-device. Every decision, signal, and outcome stored locally. 100% private. Learns from your own usage.",
            },
            {
              layer: "Layer 2", title: "Org Intelligence", color: "text-warning", bg: "bg-warning/10 border-warning/20",
              desc: "Supabase cloud. Patterns shared across all agents in your org. Org admins set policies that all agents follow automatically.",
            },
            {
              layer: "Layer 3", title: "Collective Pool", color: "text-success", bg: "bg-success/10 border-success/20",
              desc: "Cross-org anonymized patterns. Opt-in. Your agents benefit from the collective wisdom of the entire network.",
            },
          ].map((l) => (
            <div key={l.layer} className={`p-4 rounded-xl border ${l.bg}`}>
              <div className={`text-xs font-bold ${l.color} mb-1`}>{l.layer}</div>
              <div className="text-sm font-semibold text-white mb-2">{l.title}</div>
              <p className="text-xs text-muted">{l.desc}</p>
            </div>
          ))}
        </div>

        <div className="p-4 rounded-xl bg-bg-elevated border border-bg-border">
          <div className="text-xs font-semibold text-white mb-2">The judgment loop:</div>
          <div className="flex items-center gap-2 text-xs text-muted flex-wrap">
            {["Agent calls tool", "→", "Sentigent evaluates", "→", "proceed / slow_down / escalate", "→", "Agent acts", "→", "Outcome recorded", "→", "Score improves"].map((s, i) => (
              <span key={i} className={s === "→" ? "text-muted/40" : "text-white/70"}>{s}</span>
            ))}
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "install",
    title: "Install Sentigent",
    role: "developer",
    icon: <Terminal size={16} />,
    description: "Install the package and configure MCP hooks",
    estimatedMin: 5,
    content: (
      <div className="space-y-4">
        <p className="text-sm text-white/80">Install via pip and set up MCP hooks in your Claude Code config.</p>

        <div>
          <div className="text-xs text-muted mb-2">1. Install the package</div>
          <CodeBlock code={`pip install "sentigent[dashboard,mcp]"`} />
        </div>

        <div>
          <div className="text-xs text-muted mb-2">2. Add MCP server to <code className="font-mono text-accent-light">~/.claude/claude_desktop_config.json</code></div>
          <CodeBlock language="json" code={`{
  "mcpServers": {
    "sentigent": {
      "command": "python",
      "args": ["-m", "sentigent.mcp_server"],
      "env": {
        "SENTIGENT_AGENT_ID": "your_name",
        "SENTIGENT_ORG_ID": "${orgSlug}"
      }
    }
  }
}`} />
        </div>

        <div>
          <div className="text-xs text-muted mb-2">3. Add PreToolUse / PostToolUse hooks to <code className="font-mono text-accent-light">~/.claude/settings.json</code></div>
          <CodeBlock language="json" code={`{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash|Write|Edit",
      "hooks": [{"type": "command", "command": "python -m sentigent.hooks.pre_tool_use"}]
    }],
    "PostToolUse": [{
      "matcher": "Bash|Write|Edit",
      "hooks": [{"type": "command", "command": "python -m sentigent.hooks.post_tool_use"}]
    }]
  }
}`} />
        </div>

        <div className="p-3 rounded-lg bg-success-dim border border-success/20 text-xs text-success">
          ✓ That's it! Every Bash, Write, and Edit call is now intercepted and evaluated automatically.
        </div>
      </div>
    ),
  },
  {
    id: "configure-org",
    title: "Connect Your Org",
    role: "admin",
    icon: <Globe size={16} />,
    description: "Set up Supabase for Layer 2 org-wide intelligence",
    estimatedMin: 10,
    content: (
      <div className="space-y-4">
        <p className="text-sm text-white/80">Layer 2 requires a Supabase project for cross-agent org intelligence and policy enforcement.</p>

        <div>
          <div className="text-xs text-muted mb-2">1. Run the Supabase migration</div>
          <CodeBlock code={`# From your sentigent project root
supabase db push
# Or apply the migration manually from:
# sentigent/db/migrations/`} />
        </div>

        <div>
          <div className="text-xs text-muted mb-2">2. Add to your team's <code className="font-mono text-accent-light">.env</code></div>
          <CodeBlock language="bash" code={`SUPABASE_URL=${supabaseUrl}
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>
SENTIGENT_ORG_ID=${orgSlug}
SENTIGENT_SUPABASE_ORG_ID=${orgId}`} />
        </div>

        <div>
          <div className="text-xs text-muted mb-2">3. Verify the connection</div>
          <CodeBlock code={`python -m sentigent.cli prove --days 7`} />
        </div>

        <div className="p-3 rounded-lg bg-info/10 border border-info/20 text-xs text-info">
          💡 Share the same SUPABASE_URL and org UUID with all team members so their agents contribute to the shared org pool.
        </div>
      </div>
    ),
  },
  {
    id: "first-policies",
    title: "Deploy Your First Policies",
    role: "admin",
    icon: <ShieldCheck size={16} />,
    description: "Create org-wide safety guardrails in minutes",
    estimatedMin: 5,
    content: (
      <div className="space-y-4">
        <p className="text-sm text-white/80">
          Start with the built-in practice templates. Go to{" "}
          <strong className="text-accent-light">Policy Manager → Practice Templates</strong>{" "}
          and apply these three to get started immediately:
        </p>

        <div className="space-y-2">
          {[
            {
              name: "no_force_push",
              why: "Prevents accidental history destruction. Block force pushes to protected branches.",
              impact: "critical",
            },
            {
              name: "protect_env_files",
              why: "Escalates any write to .env, credentials, or secret files for human review.",
              impact: "critical",
            },
            {
              name: "no_secrets_in_code",
              why: "Blocks agents from hardcoding API keys or passwords directly in source files.",
              impact: "critical",
            },
          ].map((p) => (
            <div key={p.name} className="flex items-start gap-3 p-3 rounded-lg bg-bg-elevated border border-bg-border">
              <ShieldCheck size={14} className="text-success mt-0.5 shrink-0" />
              <div>
                <div className="text-xs font-mono font-semibold text-white">{p.name}</div>
                <div className="text-[11px] text-muted">{p.why}</div>
              </div>
              <span className="ml-auto text-[10px] text-danger font-medium">critical</span>
            </div>
          ))}
        </div>

        <p className="text-xs text-muted">
          Once applied, these policies are enforced for <strong className="text-white">every agent in your org</strong>{" "}
          — no per-agent configuration needed.
        </p>
      </div>
    ),
  },
  {
    id: "first-evaluation",
    title: "Run Your First Evaluation",
    role: "developer",
    icon: <PlayCircle size={16} />,
    description: "See Sentigent in action — your first judgment call",
    estimatedMin: 2,
    content: (
      <div className="space-y-4">
        <p className="text-sm text-white/80">
          In a Claude Code session, Sentigent intercepts every tool call automatically via hooks.
          You can also call it explicitly:
        </p>

        <div>
          <div className="text-xs text-muted mb-2">Manual evaluation (in Claude Code):</div>
          <CodeBlock language="typescript" code={`// Call the sentigent_evaluate MCP tool
sentigent_evaluate(
  tool_name="Bash",
  tool_input="git push origin main --force",
  context='{"reason": "need to push urgently", "confidence": 0.8}'
)

// Response:
// {
//   "action": "escalate",
//   "reason": "Force push detected — policy 'no_force_push' requires human approval",
//   "judgment_score": 0.82
// }`} />
        </div>

        <div>
          <div className="text-xs text-muted mb-2">Record the outcome after action:</div>
          <CodeBlock language="typescript" code={`sentigent_outcome(trace_id="...", outcome="correct")
// or "incorrect" if the judgment was wrong`} />
        </div>

        <div className="p-3 rounded-lg bg-accent/10 border border-accent/20 text-xs">
          <div className="text-accent-light font-semibold mb-1">Why outcomes matter</div>
          <p className="text-white/70">
            Each outcome improves the Brier Score — a calibration metric for how well judgment scores predict real risk.
            After 20+ outcomes, your agents develop genuine situational judgment.
          </p>
        </div>
      </div>
    ),
  },
  {
    id: "build-prompts",
    title: "Build Better Prompts",
    role: "developer",
    icon: <Sparkles size={16} />,
    description: "Use the Prompt Builder to write structured, high-quality tasks",
    estimatedMin: 3,
    content: (
      <div className="space-y-4">
        <p className="text-sm text-white/80">
          Vague prompts produce vague results. The Sentigent Prompt Builder guides you through structured templates
          that auto-invoke the right Claude Code skill.
        </p>

        <div>
          <div className="text-xs text-muted mb-2">Via MCP tool (in Claude Code):</div>
          <CodeBlock language="typescript" code={`sentigent_prompt_build({action: "list"})
// → Lists all 7 templates

sentigent_prompt_build({action: "start", template: "bug_report"})
// → Asks Q1: "What is the bug summary?"

sentigent_prompt_build({action: "answer", session_id: "...", answer: "Login fails on Firefox"})
// → Asks Q2, Q3... until prompt is complete

// On completion:
// {
//   "status": "complete",
//   "prompt": "## Bug Report\n...",
//   "skill_to_invoke": "debug"
// }
// → Auto-invokes /debug skill with the assembled prompt`} />
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs">
          {[
            { t: "product_spec", s: "feature-dev" },
            { t: "bug_report", s: "debug" },
            { t: "pr_review", s: "code-review" },
            { t: "code_refactor", s: "refactor" },
          ].map((m) => (
            <div key={m.t} className="flex items-center justify-between p-2 rounded-lg bg-bg-elevated border border-bg-border">
              <span className="font-mono text-white/80">{m.t}</span>
              <span className="text-accent-light">→ /{m.s}</span>
            </div>
          ))}
        </div>
      </div>
    ),
  },
  {
    id: "prove-value",
    title: "Prove the Value",
    role: "admin",
    icon: <TrendingUp size={16} />,
    description: "Generate ROI reports for leadership",
    estimatedMin: 2,
    content: (
      <div className="space-y-4">
        <p className="text-sm text-white/80">
          After 2–4 weeks of usage, the Proof of Value page shows quantified impact:
        </p>

        <div className="space-y-2">
          {[
            { metric: "Confirmed Catches", what: "Interventions where the agent was blocked and that block was validated as correct" },
            { metric: "Intervention Accuracy", what: "% of escalations/slow-downs that were confirmed correct by the team" },
            { metric: "Brier Score", what: "Calibration metric: how well judgment scores predict real outcomes (lower = better)" },
            { metric: "Policy Enforcements", what: "Total times org policies fired automatically across all agents" },
          ].map((m) => (
            <div key={m.metric} className="flex gap-3 p-3 rounded-lg bg-bg-elevated border border-bg-border">
              <TrendingUp size={13} className="text-success shrink-0 mt-0.5" />
              <div>
                <div className="text-xs font-semibold text-white">{m.metric}</div>
                <div className="text-[11px] text-muted">{m.what}</div>
              </div>
            </div>
          ))}
        </div>

        <div>
          <div className="text-xs text-muted mb-2">Export for stakeholders:</div>
          <CodeBlock code={`python -m sentigent.cli prove --days 30 --format json > report.json`} />
        </div>
      </div>
    ),
  },
  {
    id: "team-rollout",
    title: "Roll Out to Your Team",
    role: "admin",
    icon: <Users size={16} />,
    description: "Onboard all engineers with the team configuration",
    estimatedMin: 5,
    content: (
      <div className="space-y-4">
        <p className="text-sm text-white/80">
          Once your org is configured and first policies are deployed, roll out to the team:
        </p>

        <div className="space-y-3">
          {[
            {
              step: "1",
              title: "Share the .env template",
              desc: "Give each engineer SUPABASE_URL, SENTIGENT_ORG_ID, and SENTIGENT_SUPABASE_ORG_ID. They set their own SENTIGENT_AGENT_ID.",
            },
            {
              step: "2",
              title: "Add to onboarding docs",
              desc: "Include the 'pip install + claude_desktop_config.json + settings.json' steps in your engineering onboarding runbook.",
            },
            {
              step: "3",
              title: "Monitor via Org Dashboard",
              desc: "The Org Dashboard shows all agents, their judgment scores, and which policies fired — no manual status updates needed.",
            },
            {
              step: "4",
              title: "Tune policies based on feedback",
              desc: "Start strict, then relax severity based on false positive rates. The violation audit log shows exactly what fired and when.",
            },
          ].map((s) => (
            <div key={s.step} className="flex gap-3 p-3 rounded-xl bg-bg-elevated border border-bg-border">
              <div className="w-5 h-5 rounded-full bg-accent/20 border border-accent/30 flex items-center justify-center text-[10px] text-accent-light font-bold shrink-0 mt-0.5">
                {s.step}
              </div>
              <div>
                <div className="text-xs font-semibold text-white mb-0.5">{s.title}</div>
                <div className="text-[11px] text-muted">{s.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    ),
  },
  ];
}

export function Onboarding() {
  const navigate = useNavigate();
  const { membership } = useAuth();
  const onNavigate = (page: NavPage) => navigate(`/${page}`);
  const [role, setRole] = useState<"admin" | "developer">("admin");
  const [activeStep, setActiveStep] = useState(0);
  const [completed, setCompleted] = useState<Set<string>>(new Set());

  const supabaseUrl = (import.meta.env.VITE_SUPABASE_URL as string) || "https://your-project.supabase.co";
  const orgSlug = membership?.org_slug || "your_org";
  const orgId = membership?.org_id || "your-supabase-org-uuid";

  const STEPS = useMemo(
    () => buildSteps(orgSlug, orgId, supabaseUrl),
    [orgSlug, orgId, supabaseUrl],
  );

  const filteredSteps = STEPS.filter((s) => s.role === "all" || s.role === role);
  const current = filteredSteps[activeStep];
  const totalMin = filteredSteps.reduce((s, st) => s + st.estimatedMin, 0);

  function complete(stepId: string) {
    setCompleted((prev) => new Set([...prev, stepId]));
    if (activeStep < filteredSteps.length - 1) {
      setActiveStep((n) => n + 1);
    }
  }

  const QUICK_ACTIONS: Array<{ label: string; page: NavPage; icon: React.ReactNode }> = [
    { label: "Org Dashboard", page: "dashboard", icon: <Activity size={14} /> },
    { label: "Deploy Policies", page: "policies", icon: <ShieldCheck size={14} /> },
    { label: "Build Prompt", page: "prompt-builder", icon: <Sparkles size={14} /> },
    { label: "Proof of Value", page: "proof", icon: <TrendingUp size={14} /> },
  ];

  return (
    <div className="p-6 space-y-6 animate-fade-in max-w-5xl mx-auto">
      {/* Hero */}
      <div className="relative p-6 rounded-2xl overflow-hidden border border-accent/25"
        style={{ background: "linear-gradient(135deg, rgba(124,58,237,0.12) 0%, rgba(13,17,23,1) 60%)" }}>
        {/* Glow orb */}
        <div className="absolute top-0 right-0 w-64 h-64 pointer-events-none"
          style={{ background: "radial-gradient(circle at 80% 10%, rgba(124,58,237,0.15) 0%, transparent 60%)" }} />
        <div className="flex items-start gap-5 relative">
          <div className="w-14 h-14 rounded-2xl bg-gradient-accent flex items-center justify-center shadow-glow shrink-0 animate-float">
            <Activity size={24} className="text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2 mb-2">
              <h1 className="text-xl font-bold text-white">Welcome to Sentigent</h1>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent/15 text-accent-light border border-accent/20 font-semibold">
                v1.0
              </span>
            </div>
            <p className="text-sm text-muted/90 max-w-xl leading-relaxed">
              The enterprise AI judgment layer for coding agents — self-learning, policy-enforcing, and quantifiable.
              Think of it as <strong className="text-accent-light">ServiceNow for your AI agents</strong>: governance,
              compliance, and proof of value baked in.
            </p>
            <div className="flex items-center gap-4 mt-3 text-xs text-muted">
              <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-success" />3-layer architecture</span>
              <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-accent-light" />Self-learning</span>
              <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-warning" />Policy enforcement</span>
            </div>
          </div>
        </div>
      </div>

      {/* Role selector */}
      <div className="flex items-center gap-3">
        <span className="text-xs text-muted font-medium">I am a:</span>
        <div className="flex rounded-xl border border-bg-border overflow-hidden bg-bg-elevated/50">
          {(["admin", "developer"] as const).map((r) => (
            <button
              key={r}
              onClick={() => { setRole(r); setActiveStep(0); }}
              className={`px-4 py-2 text-xs font-semibold transition-all ${
                role === r
                  ? "bg-accent/20 text-white border-r border-accent/20 last:border-r-0"
                  : "text-muted hover:text-white border-r border-bg-border last:border-r-0"
              }`}
            >
              {r === "admin" ? "Org Admin" : "Developer"}
            </button>
          ))}
        </div>
        <span className="text-xs text-muted">~{totalMin} min</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Step List */}
        <div className="space-y-1">
          {filteredSteps.map((step, idx) => {
            const isActive = idx === activeStep;
            const isDone = completed.has(step.id);

            return (
              <button
                key={step.id}
                onClick={() => setActiveStep(idx)}
                className={`w-full text-left px-3 py-3 rounded-lg border transition-all ${
                  isActive
                    ? "bg-accent/10 border-accent/30 text-white"
                    : "border-transparent text-muted hover:bg-bg-elevated hover:text-white"
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`shrink-0 ${isDone ? "text-success" : isActive ? "text-accent-light" : "text-muted"}`}>
                    {isDone ? <CheckCircle2 size={16} /> : <Circle size={16} />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-semibold truncate">{step.title}</div>
                    <div className="text-[10px] text-muted">{step.estimatedMin} min</div>
                  </div>
                  <RoleBadge role={step.role} />
                </div>
              </button>
            );
          })}

          {/* Quick Actions */}
          <div className="pt-4 border-t border-bg-border mt-4">
            <div className="text-[10px] text-muted uppercase tracking-wider mb-2 px-3">Quick actions</div>
            {QUICK_ACTIONS.map((a) => (
              <button
                key={a.page}
                onClick={() => onNavigate(a.page)}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted hover:text-white hover:bg-bg-elevated rounded-lg transition-colors"
              >
                <span className="text-accent-light">{a.icon}</span>
                {a.label}
                <ArrowRight size={10} className="ml-auto" />
              </button>
            ))}
          </div>
        </div>

        {/* Step Content */}
        {current && (
          <div className="lg:col-span-2">
            <Card>
              <div className="px-6 py-5 border-b border-bg-border">
                <div className="flex items-center gap-3 mb-1">
                  <span className="text-accent-light">{current.icon}</span>
                  <h2 className="text-sm font-semibold text-white">{current.title}</h2>
                  <RoleBadge role={current.role} />
                </div>
                <p className="text-xs text-muted">{current.description}</p>
              </div>
              <CardBody className="space-y-5">
                {current.content}

                <div className="flex items-center justify-between pt-4 border-t border-bg-border">
                  <button
                    onClick={() => activeStep > 0 && setActiveStep((n) => n - 1)}
                    disabled={activeStep === 0}
                    className="text-xs text-muted hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    ← Previous
                  </button>

                  <div className="flex items-center gap-1">
                    {filteredSteps.map((_, i) => (
                      <div
                        key={i}
                        className={`w-1.5 h-1.5 rounded-full transition-colors ${
                          i === activeStep ? "bg-accent" : completed.has(filteredSteps[i].id) ? "bg-success" : "bg-bg-border"
                        }`}
                      />
                    ))}
                  </div>

                  <button
                    onClick={() => complete(current.id)}
                    className="flex items-center gap-2 px-4 py-2 text-xs font-medium bg-accent hover:bg-accent/80 text-white rounded-lg transition-colors"
                  >
                    {completed.has(current.id) ? "Next" : "Mark complete"}
                    <ChevronRight size={12} />
                  </button>
                </div>
              </CardBody>
            </Card>
          </div>
        )}
      </div>

      {/* Progress summary */}
      {completed.size > 0 && (
        <div className="p-4 rounded-xl bg-success-dim border border-success/20 flex items-center gap-3">
          <CheckCircle2 size={16} className="text-success shrink-0" />
          <div className="flex-1">
            <div className="text-xs font-semibold text-white">
              {completed.size}/{filteredSteps.length} steps completed
            </div>
            <div className="text-[11px] text-muted">
              {completed.size === filteredSteps.length
                ? "You're all set! Head to the Org Dashboard to see your agents."
                : "Keep going — each step builds on the previous."}
            </div>
          </div>
          {completed.size === filteredSteps.length && (
            <button
              onClick={() => onNavigate("dashboard")}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-success/20 hover:bg-success/30 text-success border border-success/30 rounded-lg transition-colors"
            >
              <Zap size={12} />
              Go to Dashboard
            </button>
          )}
        </div>
      )}

      {/* Reference Links */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { title: "MCP Tools Reference", desc: "All 19 MCP tools with examples", icon: <Terminal size={14} /> },
          { title: "Policy Templates", desc: "10 built-in practice policies", icon: <ShieldCheck size={14} /> },
          { title: "Prompt Templates", desc: "7 workflow templates", icon: <Sparkles size={14} /> },
          { title: "Brier Score Guide", desc: "Understanding calibration", icon: <BookOpen size={14} /> },
        ].map((ref) => (
          <div key={ref.title} className="p-3 rounded-lg bg-bg-surface border border-bg-border hover:border-accent/30 transition-colors cursor-default">
            <div className="text-accent-light mb-2">{ref.icon}</div>
            <div className="text-xs font-semibold text-white mb-0.5">{ref.title}</div>
            <div className="text-[10px] text-muted">{ref.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
