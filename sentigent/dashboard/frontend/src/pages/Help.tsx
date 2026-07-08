/**
 * Help / Documentation page — complete technical reference for Sentigent.
 *
 * Sections:
 *   Overview     — what Sentigent is, the 3-layer model
 *   Quick Start  — install, configure, use in 5 minutes
 *   Core Concepts — profiles, signals, decisions, episodes, outcomes, patterns
 *   Intelligence Hub — AgentHub, Learner, LLMJudge, AgentBus, Executor
 *   Org Policies — Layer 2 governance and enforcement rules
 *   Collective Intel — Layer 3 cross-org pattern sharing
 *   REST API     — all endpoints with parameters and responses
 *   MCP Tools    — all Claude Code hook tools
 *   Configuration — sentigent.toml, environment variables
 *   Proof of Value — /prove command, metrics
 */
import { useState } from "react";
import {
  BookOpen, Cpu, Network, ShieldCheck, Globe, Zap, Code2,
  Terminal, Settings, TrendingUp, ChevronRight, Copy, Check,
} from "lucide-react";

// ── Section registry ─────────────────────────────────────────────────────────

type SectionId =
  | "overview" | "quickstart" | "concepts" | "intelligence"
  | "policies" | "collective" | "api" | "mcp" | "config" | "prove";

interface Section {
  id: SectionId;
  label: string;
  icon: React.ReactNode;
}

const SECTIONS: Section[] = [
  { id: "overview",      label: "Overview",            icon: <BookOpen size={14} /> },
  { id: "quickstart",    label: "Quick Start",         icon: <Zap size={14} /> },
  { id: "concepts",      label: "Core Concepts",       icon: <Cpu size={14} /> },
  { id: "intelligence",  label: "Intelligence Hub",    icon: <Network size={14} /> },
  { id: "policies",      label: "Org Policies",        icon: <ShieldCheck size={14} /> },
  { id: "collective",    label: "Collective Intel",    icon: <Globe size={14} /> },
  { id: "api",           label: "REST API",            icon: <Code2 size={14} /> },
  { id: "mcp",           label: "MCP Tools",           icon: <Terminal size={14} /> },
  { id: "config",        label: "Configuration",       icon: <Settings size={14} /> },
  { id: "prove",         label: "Proof of Value",      icon: <TrendingUp size={14} /> },
];

// ── Reusable primitives ───────────────────────────────────────────────────────

function CodeBlock({ code, lang = "python" }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(code.trim());
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };
  return (
    <div className="relative rounded-xl border border-bg-border/60 overflow-hidden my-3 group">
      <div className="flex items-center justify-between px-4 py-2 border-b border-bg-border/40"
        style={{ background: "rgba(255,255,255,0.03)" }}>
        <span className="text-[10px] text-muted/50 font-mono uppercase tracking-wider">{lang}</span>
        <button onClick={copy}
          className="flex items-center gap-1 text-[10px] text-muted/40 hover:text-muted/70 transition-colors">
          {copied ? <><Check size={11} className="text-emerald-400" /> Copied</> : <><Copy size={11} /> Copy</>}
        </button>
      </div>
      <pre className="text-xs text-muted/80 p-4 overflow-x-auto font-mono leading-relaxed"
        style={{ background: "#07090f" }}>
        <code>{code.trim()}</code>
      </pre>
    </div>
  );
}

function H2({ children }: { children: React.ReactNode }) {
  return <h2 className="text-base font-bold text-white mt-7 mb-3 flex items-center gap-2">{children}</h2>;
}
function H3({ children }: { children: React.ReactNode }) {
  return <h3 className="text-sm font-semibold text-white/90 mt-5 mb-2">{children}</h3>;
}
function P({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted/70 leading-relaxed mb-2">{children}</p>;
}
function Li({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2 text-sm text-muted/70 mb-1.5">
      <ChevronRight size={12} className="text-accent-light mt-0.5 flex-shrink-0" />
      <span>{children}</span>
    </li>
  );
}
function Table({ head, rows }: { head: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto my-3 rounded-xl border border-bg-border/50">
      <table className="w-full text-xs">
        <thead>
          <tr style={{ background: "rgba(124,58,237,0.08)" }}>
            {head.map((h, i) => (
              <th key={i} className="text-left px-3 py-2 text-muted/60 font-semibold uppercase tracking-wider border-b border-bg-border/40">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className="border-b border-bg-border/30 last:border-0 hover:bg-white/[0.02]">
              {row.map((cell, ci) => (
                <td key={ci} className={`px-3 py-2 ${ci === 0 ? "font-mono text-accent-light/80" : "text-muted/70"}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Badge({ children, color = "accent" }: { children: React.ReactNode; color?: string }) {
  const cls: Record<string, string> = {
    accent: "text-violet-400 bg-violet-400/10 border-violet-400/30",
    green: "text-emerald-400 bg-emerald-400/10 border-emerald-400/30",
    amber: "text-amber-400 bg-amber-400/10 border-amber-400/30",
    red: "text-red-400 bg-red-400/10 border-red-400/30",
  };
  return (
    <span className={`inline text-[10px] px-1.5 py-0.5 rounded border font-mono font-medium mx-0.5 ${cls[color] || cls.accent}`}>
      {children}
    </span>
  );
}
function Callout({ type = "info", children }: { type?: "info" | "warning" | "tip"; children: React.ReactNode }) {
  const styles = {
    info: "border-blue-400/30 bg-blue-400/5 text-blue-300/80",
    warning: "border-amber-400/30 bg-amber-400/5 text-amber-300/80",
    tip: "border-emerald-400/30 bg-emerald-400/5 text-emerald-300/80",
  };
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm my-3 leading-relaxed ${styles[type]}`}>
      {children}
    </div>
  );
}

// ── Section content ───────────────────────────────────────────────────────────

function OverviewSection() {
  return (
    <div>
      <P>
        <strong className="text-white">Sentigent</strong> is a self-learning AI judgment layer that wraps any
        AI agent and teaches it better decision-making over time. It evaluates every action before it's taken,
        records outcomes, and autonomously improves its accuracy — getting smarter with every decision.
      </P>
      <H2>The 3-Layer Architecture</H2>
      <Table
        head={["Layer", "Name", "Scope", "What it does"]}
        rows={[
          ["Layer 1", "Agent Memory", "Per-agent, local", "SQLite episodic memory, signal computation, procedural rule learning. Zero dependencies."],
          ["Layer 2", "Org Intelligence", "Per-org, Supabase", "Policy enforcement, org-wide patterns, collective baselines. Agents share learning across the org."],
          ["Layer 3", "Collective Pool", "Cross-org, opt-in", "Anonymized pattern sharing across organisations. Contributes to and draws from the global wisdom pool."],
        ]}
      />
      <H2>Decision Flow</H2>
      <CodeBlock lang="text" code={`
User agent action
      │
      ▼
[1] Org policy check (Layer 2)          ← highest priority, deterministic
      │  match → enforce_action returned immediately
      │  no match ↓
[2] Procedural rule check (Layer 1)     ← high-confidence learned patterns
      │  >90% success + n>50 → action returned immediately
      │  no match ↓
[3] Signal computation                  ← 5 signals: caution, doubt, urgency,
      │                                    confidence, frustration
      ▼
[4] Decision gate                       ← threshold comparison → action
      │
      ▼
[5] LLM Judge enrichment               ← Claude (ambiguous zone 0.30-0.70 only)
      │  peer patterns from hub injected as context
      ▼
[6] Action Executor                    ← escalate event, slow_down delay,
      │                                    enrich context fetch
      ▼
Decision returned to agent
( proceed | slow_down | enrich | escalate )
`} />
      <H2>Signal Types</H2>
      <Table
        head={["Signal", "Meaning", "Typical triggers"]}
        rows={[
          ["caution", "General risk indicator", "High transaction amounts, first-time patterns, sensitive files"],
          ["doubt", "Uncertainty / low confidence", "Ambiguous task descriptions, conflicting context"],
          ["urgency", "Time pressure detected", "Retry counts, deadline keywords, escalating context"],
          ["confidence", "Certainty — LOWERS risk", "Familiar pattern, recent success, high outcome history"],
          ["frustration", "Repeated failures", "Multiple retries, error loop context"],
        ]}
      />
    </div>
  );
}

function QuickStartSection() {
  return (
    <div>
      <H2>Installation</H2>
      <CodeBlock lang="bash" code={`
# From the repo
pip install -e .

# Or from PyPI (when published)
pip install sentigent
`} />
      <H2>Minimal Usage</H2>
      <CodeBlock lang="python" code={`
from sentigent import Sentigent

judge = Sentigent(profile="default", agent_id="my-agent")

# Before every action:
decision = judge.evaluate(
    task="Delete all records from orders table",
    context={"table": "orders", "record_count": 50000},
)
print(decision.action)   # "escalate"
print(decision.reason)   # "High record count + irreversible operation"

# After you know the outcome:
judge.record_outcome(decision.trace_id, "correct")
`} />
      <H2>Claude Code Hook (MCP)</H2>
      <P>Add to <code className="text-accent-light/80 font-mono text-xs">.claude/settings.json</code> to activate passive pre/post tool hooks:</P>
      <CodeBlock lang="json" code={`
{
  "mcpServers": {
    "sentigent": {
      "command": "python",
      "args": ["-m", "sentigent.mcp_server"],
      "env": {
        "SENTIGENT_AGENT_ID": "claude-code",
        "SENTIGENT_ORG_ID": "your-org-slug",
        "SUPABASE_URL": "https://xxx.supabase.co",
        "SUPABASE_ANON_KEY": "eyJ..."
      }
    }
  }
}
`} />
      <H2>With a Domain Profile</H2>
      <CodeBlock lang="python" code={`
# Domain profiles tune signal thresholds for your industry
judge = Sentigent(profile="financial_ops")    # conservative
judge = Sentigent(profile="devops")           # moderate
judge = Sentigent(profile="content_creation") # permissive

# Check available profiles
from sentigent.profiles.registry import list_profiles
print(list_profiles())
`} />
      <H2>Environment Variables</H2>
      <Table
        head={["Variable", "Required", "Purpose"]}
        rows={[
          ["SENTIGENT_ORG_ID", "Layer 2", "Your org slug (e.g. 'acme'). Enables Supabase sync."],
          ["SENTIGENT_AGENT_ID", "No", "Agent identifier. Defaults to hostname."],
          ["SUPABASE_URL", "Layer 2", "Supabase project URL."],
          ["SUPABASE_ANON_KEY", "Layer 2", "Supabase anon key for client auth."],
          ["SUPABASE_SERVICE_ROLE_KEY", "Layer 2 admin", "Service role key for server-side operations."],
          ["ANTHROPIC_API_KEY", "LLM Judge", "Required for Claude-powered enrichment in ambiguous cases."],
          ["SENTIGENT_PROFILE", "No", "Default profile name. Overridden by Sentigent(profile=...)."],
          ["SENTIGENT_DB_PATH", "No", "SQLite path. Defaults to ~/.sentigent/memory.db."],
        ]}
      />
    </div>
  );
}

function ConceptsSection() {
  return (
    <div>
      <H2>Profiles</H2>
      <P>Profiles encode domain-specific thresholds and signal weights. They determine how aggressively the gate reacts to signals.</P>
      <Table
        head={["Profile", "Caution threshold", "Use case"]}
        rows={[
          ["default", "0.45", "General-purpose balanced judgment"],
          ["financial_ops", "0.35", "High-stakes financial operations"],
          ["devops", "0.50", "Infrastructure and deployment"],
          ["content_creation", "0.65", "Low-risk content tasks"],
          ["healthcare", "0.30", "Medical/compliance contexts"],
          ["legal_review", "0.30", "Legal document operations"],
        ]}
      />
      <H2>Episodes (Episodic Memory)</H2>
      <P>Every <code className="text-accent-light/80 font-mono text-xs">evaluate()</code> call produces an Episode stored in SQLite (Layer 1):</P>
      <Table
        head={["Field", "Type", "Description"]}
        rows={[
          ["trace_id", "UUID", "Unique ID linking decision to outcome"],
          ["task", "string", "Task description (truncated to 500 chars)"],
          ["decision", "enum", "proceed | slow_down | enrich | escalate"],
          ["outcome", "enum | null", "correct | incorrect | neutral (set via record_outcome)"],
          ["confidence_at_decision", "float", "0–1 confidence score at decision time"],
          ["signals", "dict", "Signal strengths: {caution: 0.7, doubt: 0.3, ...}"],
          ["timestamp", "ISO-8601", "When the evaluation happened"],
          ["agent_id", "string", "Which agent produced this episode"],
          ["policy_name", "string?", "Set if episode was triggered by a policy"],
        ]}
      />
      <H2>Procedural Rules (Pattern Learning)</H2>
      <P>After recording enough outcomes, Sentigent mines recurring patterns and stores them as procedural rules. Rules with <Badge color="green">success_rate &gt; 0.90</Badge> and <Badge>n &gt; 50</Badge> become fast-path shortcuts — bypassing signal computation entirely.</P>
      <CodeBlock lang="python" code={`
# Mine patterns manually (auto-triggered every 50 outcomes)
judge._pattern_miner.mine(episodes)

# Inspect local rules
rules = judge._memory.get_matching_rules({})
for rule in rules:
    print(rule["pattern_name"], rule["success_rate"], rule["sample_size"])
`} />
      <H2>Decision Actions</H2>
      <Table
        head={["Action", "Meaning", "Agent should..."]}
        rows={[
          ["proceed", "Low risk, go ahead", "Execute the action normally"],
          ["slow_down", "Elevated risk, but ok", "Add extra validation, log warnings, notify human if sensitive"],
          ["enrich", "Needs more context", "Gather additional information before acting"],
          ["escalate", "High risk — stop", "Block the action, ask human for approval"],
        ]}
      />
      <H2>Brier Score</H2>
      <P>The judgment score is computed as a Brier score: mean squared error between predicted confidence and binary outcome (correct=1, incorrect=0). Lower is better. Values &lt;0.25 indicate good calibration.</P>
      <CodeBlock lang="python" code={`
# Get current judgment score
print(judge.judgment_score)   # 0.82 = 82% correct decisions rated

# Via CLI
sentigent score
`} />
    </div>
  );
}

function IntelligenceSection() {
  return (
    <div>
      <H2>Architecture</H2>
      <P>The Intelligence Hub is a singleton that all agents in an org automatically connect to. It forms the autonomous self-improvement backbone.</P>
      <CodeBlock lang="text" code={`
sentigent/intelligence/
  hub.py        — AgentHub: central intelligence hub (singleton)
  connector.py  — AgentConnector: agent registration + signal pub/sub
  llm_judge.py  — LLMJudge: Claude reasoning for ambiguous decisions
  learner.py    — CollectiveLearner: background 30s self-improvement loop
  agent_bus.py  — AgentBus: inter-agent messaging + capability routing
  executor.py   — ActionExecutor: decision → concrete side-effects
`} />
      <H2>AgentHub</H2>
      <P>Singleton started automatically when <code className="text-accent-light/80 font-mono text-xs">Sentigent()</code> is initialized. All agents in the same process share one hub.</P>
      <CodeBlock lang="python" code={`
from sentigent.intelligence import get_hub

hub = get_hub(org_id="my-org")     # singleton
hub.connect("agent-id")            # register

# Inspect hub
status = hub.status()
print(status.connected_agents)
print(status.learner_report)

# Get peer patterns (success_rate > 0.80)
patterns = hub.get_peer_patterns(limit=10)

# Network view
agents = hub.get_agent_network()
`} />
      <H2>CollectiveLearner</H2>
      <P>Background thread running every 30 seconds. No human trigger needed.</P>
      <ul className="my-2">
        <Li><strong className="text-white/80">Bayesian threshold optimization</strong> — grid-searches optimal caution/doubt/confidence thresholds per agent using beta distributions over outcome history.</Li>
        <Li><strong className="text-white/80">Auto-policy generation</strong> — patterns with success_rate &gt; 0.95 and n &gt; 50 are automatically promoted to org_policies in Supabase.</Li>
        <Li><strong className="text-white/80">Cross-agent insights</strong> — aggregates patterns across all org agents, surfaces regressions and emerging trends.</Li>
        <Li><strong className="text-white/80">Regression detection</strong> — compares last 3 cycles vs baseline; flags &gt;5% drop in accuracy.</Li>
      </ul>
      <CodeBlock lang="python" code={`
# Force immediate learning cycle (usually runs automatically)
report = hub._learner.run_once()
print(report.threshold_updates)    # [{signal, old, new, gain}]
print(report.policies_generated)   # [policy_name, ...]
print(report.cross_agent_insights) # ["Agent A showing regression...", ...]
print(report.regression_detected)  # bool
`} />
      <H2>LLM Judge</H2>
      <P>Claude-powered reasoning for ambiguous decisions. Only triggered when:</P>
      <ul className="my-2">
        <Li>Caution signal is in the ambiguous zone: <Badge>0.30 – 0.70</Badge></Li>
        <Li>Signals conflict: caution &gt; 0.5 AND confidence &gt; 0.5</Li>
        <Li>Action is <Badge color="red">escalate</Badge> (always re-examined)</Li>
      </ul>
      <Table
        head={["Condition", "Model used"]}
        rows={[
          ["Default (fast path)", "claude-haiku-4-5 — sub-1s, cached 60s"],
          ["Escalation / high-conflict", "claude-sonnet-4-6 — higher quality"],
        ]}
      />
      <P>The judge receives: task, signals, gate decision, similar episodes from memory, AND peer patterns from hub. This gives it full org-level context, not just local agent history.</P>
      <H2>AgentBus</H2>
      <P>Inter-agent messaging and capability routing above the connector.</P>
      <CodeBlock lang="python" code={`
from sentigent.intelligence import get_agent_bus

bus = get_agent_bus()

# Register agent with capabilities
bus.register("security-scanner", capabilities=["scan", "audit"])
bus.register("code-reviewer", capabilities=["review", "lint"])

# Listen for messages
def handle_msg(msg):
    print(msg.msg_type, msg.payload)
    return None   # or return a reply AgentMessage

bus.on_message("security-scanner", handle_msg)

# Direct message
bus.send("code-reviewer", "security-scanner",
         msg_type="task_delegate",
         payload={"code": "..."})

# Capability routing — delegate to best agent
reply = bus.delegate("code-reviewer", "scan",
                     payload={"file": "main.py"}, timeout_s=5.0)

# Org-wide broadcast
bus.broadcast("hub", msg_type="pattern_discovered",
              payload={"pattern_name": "..."})
`} />
      <H2>ActionExecutor</H2>
      <P>Fires concrete side-effects after every <code className="text-accent-light/80 font-mono text-xs">evaluate()</code>. Pluggable.</P>
      <Table
        head={["Action", "Plugin", "Side-effect"]}
        rows={[
          ["proceed", "ProceedPlugin", "No-op, fast path"],
          ["slow_down", "SlowDownPlugin", "500ms delay + warning log"],
          ["escalate", "EscalatePlugin", "EventBus escalation event + all registered webhooks"],
          ["enrich", "EnrichPlugin", "Auto-fetches peer patterns, returns in enriched_context"],
        ]}
      />
      <CodeBlock lang="python" code={`
from sentigent.intelligence import get_executor
from sentigent.events import get_event_bus, EVENT_ESCALATION

executor = get_executor()

# Register a custom Slack notifier
class SlackPlugin:
    name = "slack"
    def can_handle(self, action): return action == "escalate"
    def execute(self, ctx, result):
        requests.post(SLACK_WEBHOOK, json={"text": f"ESCALATION: {ctx.task}"})

executor.register_plugin(SlackPlugin())

# View execution stats
print(executor.get_stats())
# {"escalate": {"count": 3, "avg_latency_ms": 1.2}, ...}
`} />
    </div>
  );
}

function PoliciesSection() {
  return (
    <div>
      <H2>What Are Org Policies?</H2>
      <P>Org policies (Layer 2) are rule-based enforcement gates that apply <strong className="text-white/80">across all agents in the org simultaneously</strong>. They fire before any signal computation — they are the highest-priority override.</P>
      <Callout type="warning">Policy enforcement is deterministic and cannot be overridden by the LLM judge or procedural rules. Policies are the org admin's way to guarantee behavior.</Callout>
      <H2>Policy Fields</H2>
      <Table
        head={["Field", "Type", "Description"]}
        rows={[
          ["policy_name", "string", "Unique identifier. Used in violation logs."],
          ["trigger_tool", "enum", "Bash | Write | Edit | * (any tool)"],
          ["trigger_pattern", "regex", "Applied to tool input. Match → enforce_action fires."],
          ["enforce_action", "enum", "block | escalate | slow_down | enrich"],
          ["enforce_reason", "string", "Message shown to the agent explaining why."],
          ["severity", "enum", "low | medium | high | critical"],
          ["is_active", "bool", "Policies can be toggled without deletion."],
          ["profile_override", "string", "If set, only applies to agents using this profile."],
        ]}
      />
      <H2>Enforcement Actions</H2>
      <Table
        head={["Action", "Behaviour"]}
        rows={[
          ["block", "Hard stop — returns escalate decision. Agent must not proceed."],
          ["escalate", "Returns escalate decision + fires escalation event/webhooks."],
          ["slow_down", "Returns slow_down decision + logs warning. Agent may proceed with care."],
          ["enrich", "Returns enrich decision. Agent must gather more context first."],
        ]}
      />
      <H2>Creating Policies via MCP</H2>
      <CodeBlock lang="text" code={`
# In Claude Code:
sentigent_policy(
  action="add",
  policy_name="no_force_push",
  trigger_tool="Bash",
  trigger_pattern="push.*--force|push.*-f\\b",
  enforce_action="block",
  enforce_reason="Force push destroys history. Use --force-with-lease.",
  severity="critical"
)
`} />
      <H2>Built-in Practice Templates</H2>
      <P>Click <strong className="text-white/80">Browse templates</strong> in the Policy Manager to apply pre-built policies in one click:</P>
      <Table
        head={["Template", "Category", "Action", "Severity"]}
        rows={[
          ["TDD Enforcement", "testing", "slow_down", "medium"],
          ["No Secrets in Code", "security", "block", "critical"],
          ["No Force Push", "process", "block", "high"],
          ["Protect .env Files", "security", "escalate", "critical"],
          ["Code Review Gate", "quality", "enrich", "low"],
          ["No Production DB Mutations", "safety", "escalate", "critical"],
          ["Dependency Audit", "security", "slow_down", "medium"],
          ["No Hard Reset", "safety", "escalate", "high"],
          ["Semantic Commits", "process", "enrich", "low"],
          ["Deploy Approval Gate", "process", "escalate", "high"],
        ]}
      />
    </div>
  );
}

function CollectiveSection() {
  return (
    <div>
      <H2>How It Works</H2>
      <P>Layer 3 is an opt-in anonymized pattern pool. Orgs that opt in contribute their high-confidence patterns (success_rate &gt; 0.90, n &gt; 100) and receive patterns contributed by other participating orgs.</P>
      <Callout type="tip">No raw episodes, tasks, or org identifiers are ever shared — only the learned action and success statistics for a named pattern.</Callout>
      <H2>Opting In</H2>
      <CodeBlock lang="python" code={`
# Via the Collective Intelligence page in the dashboard
# Or via API:
POST /api/collective/opt-in
{ "profile": "financial_ops" }   # your participation profile
`} />
      <H2>What's Contributed vs Received</H2>
      <Table
        head={["Shared", "Not Shared"]}
        rows={[
          ["pattern_name", "org_id"],
          ["learned_action", "Raw tasks or inputs"],
          ["success_rate", "Agent IDs"],
          ["sample_size", "Episode content"],
          ["industry_tags (optional)", "Any identifying data"],
        ]}
      />
      <H2>Using Collective Patterns Locally</H2>
      <P>When an agent evaluates a task that matches a collective pattern with high confidence, the collective-learned action is injected as a procedural rule with a priority boost. This means orgs with few episodes still benefit from the collective.</P>
    </div>
  );
}

function ApiSection() {
  return (
    <div>
      <H2>Base URL</H2>
      <P>The dashboard server runs at <code className="text-accent-light/80 font-mono text-xs">http://localhost:7373</code> by default.</P>
      <H2>Authentication</H2>
      <P>All <code className="text-accent-light/80 font-mono text-xs">/api/</code> endpoints read the org from the authenticated Supabase session (JWT in <code className="text-accent-light/80 font-mono text-xs">Authorization</code> header) or from <code className="text-accent-light/80 font-mono text-xs">SENTIGENT_ORG_ID</code> env var for local mode.</P>

      <H3>Agent / Episode Endpoints</H3>
      <Table
        head={["Method", "Path", "Description"]}
        rows={[
          ["GET", "/api/episodes", "Paginated episode list. ?limit=50&offset=0&agent_id=&action="],
          ["GET", "/api/score", "Judgment score + outcome breakdown."],
          ["GET", "/api/timeline", "Score over time (daily buckets). ?days=30"],
          ["GET", "/api/patterns", "Learned procedural rules. ?min_success=0.7&min_samples=10"],
          ["GET", "/api/insights", "Structured analytics: correlations, trends, anomalies."],
          ["GET", "/api/baselines", "Current signal baselines with percentiles."],
        ]}
      />
      <H3>Org / Layer 2 Endpoints</H3>
      <Table
        head={["Method", "Path", "Description"]}
        rows={[
          ["GET", "/api/layer2/status", "Layer 2 config status (org_id, supabase connected)."],
          ["GET", "/api/layer2/org", "Org overview: score, all agents, patterns, baselines."],
          ["GET", "/api/layer2/org/agents", "Per-agent stats for the org."],
          ["GET", "/api/policies", "Active policies, recent violations, total count."],
          ["POST", "/api/policies", "Create a new policy. Body: OrgPolicy fields."],
          ["PATCH", "/api/policies/{name}/toggle", "Enable/disable a policy."],
          ["GET", "/api/practice-templates", "Built-in practice policy templates."],
        ]}
      />
      <H3>Intelligence Hub Endpoints</H3>
      <Table
        head={["Method", "Path", "Description"]}
        rows={[
          ["GET", "/api/intelligence/status", "Hub running state, connected agents, learner report."],
          ["GET", "/api/intelligence/network", "All connected agents with scores + capabilities."],
          ["GET", "/api/intelligence/signals", "Recent signal stream. ?agent_id=&signal_type=&limit=50"],
          ["GET", "/api/intelligence/patterns", "Peer patterns (success_rate > 0.80)."],
          ["POST", "/api/intelligence/learn", "Trigger immediate learning cycle."],
        ]}
      />
      <H3>Other Endpoints</H3>
      <Table
        head={["Method", "Path", "Description"]}
        rows={[
          ["GET", "/api/prove", "Proof of value: catches, accuracy, trajectory, top events."],
          ["GET", "/api/collective/status", "Layer 3 opt-in status + pool stats."],
          ["POST", "/api/collective/opt-in", "Opt org into Layer 3 pool. Body: {profile}."],
          ["GET", "/api/prompt-builder/templates", "List prompt builder templates."],
          ["POST", "/api/prompt-builder/start", "Start a guided prompt session."],
          ["POST", "/api/prompt-builder/answer", "Answer a prompt session question."],
          ["GET", "/api/sse/decisions", "Server-Sent Events stream of live decisions."],
        ]}
      />
    </div>
  );
}

function McpSection() {
  return (
    <div>
      <H2>Overview</H2>
      <P>Sentigent exposes all tools as an MCP (Model Context Protocol) server. Claude Code calls these tools via hooks automatically (pre/post tool use) and you can also call them explicitly.</P>
      <H2>Evaluation Tools</H2>
      <Table
        head={["Tool", "Parameters", "When to call"]}
        rows={[
          ["sentigent_evaluate", "tool_name, tool_input, context (JSON string)", "Before any risky action. Returns decision dict."],
          ["sentigent_outcome", "trace_id, outcome (correct/incorrect/neutral)", "After tests pass/fail or user confirms."],
          ["sentigent_feedback", "trace_id, was_helpful (bool)", "After user says good/bad about a decision."],
        ]}
      />
      <H2>Introspection Tools</H2>
      <Table
        head={["Tool", "Description"]}
        rows={[
          ["sentigent_score", "Judgment accuracy score, learned baselines, recent patterns."],
          ["sentigent_patterns", "All learned procedural rules with success rates."],
          ["sentigent_prove", "Full proof-of-value report: catches, accuracy, trajectory."],
        ]}
      />
      <H2>Intelligence Tools</H2>
      <Table
        head={["Tool", "Description"]}
        rows={[
          ["sentigent_hub_status", "Hub running state + learner report + connected agents."],
          ["sentigent_peer_patterns", "High-confidence org patterns (limit param). Useful before evaluate()."],
          ["sentigent_learn_now", "Force immediate learning cycle. Returns threshold updates + auto-policies."],
          ["sentigent_agent_bus", "All registered agents, capabilities, and recent bus messages."],
          ["sentigent_executor_stats", "ActionExecutor stats: per-action count + avg latency."],
        ]}
      />
      <H2>Policy Tools</H2>
      <Table
        head={["Tool", "Description"]}
        rows={[
          ["sentigent_policy(action='list')", "Show all active org policies."],
          ["sentigent_policy(action='add', ...)", "Add a new policy. Requires policy_name, trigger_tool, trigger_pattern, enforce_action."],
          ["sentigent_policy(action='disable', policy_name=...)", "Disable a policy by name."],
        ]}
      />
      <H2>Passive Hooks</H2>
      <P>If you add Sentigent as an MCP server, Claude Code automatically evaluates risky tool uses via PreToolUse hooks configured in <code className="text-accent-light/80 font-mono text-xs">.claude/settings.json</code>:</P>
      <CodeBlock lang="json" code={`
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Write|Edit",
        "hooks": [{ "type": "command", "command": "python -m sentigent.hooks pre" }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash|Write|Edit",
        "hooks": [{ "type": "command", "command": "python -m sentigent.hooks post" }]
      }
    ]
  }
}
`} />
      <H2>Example: Explicit evaluate + outcome</H2>
      <CodeBlock lang="text" code={`
# In a Claude Code session:
sentigent_evaluate(
  tool_name="Bash",
  tool_input="git push --force origin main",
  context='{"reason": "Wanted to clean history", "confidence": 0.6}'
)
# → {"action": "escalate", "reason": "No-force-push policy matched", ...}

# After user confirms it was the right call:
sentigent_outcome("trace-uuid-here", "correct")
`} />
    </div>
  );
}

function ConfigSection() {
  return (
    <div>
      <H2>sentigent.toml</H2>
      <P>Place <code className="text-accent-light/80 font-mono text-xs">sentigent.toml</code> in your project root or <code className="text-accent-light/80 font-mono text-xs">~/.sentigent/</code>. All settings can also be passed as constructor arguments.</P>
      <CodeBlock lang="toml" code={`
[sentigent]
profile = "default"                    # domain profile
agent_id = "my-agent"                  # agent identifier
org_id = "my-org"                      # org slug (Layer 2)
db_path = "~/.sentigent/memory.db"    # SQLite path
evaluate_timeout_ms = 50              # circuit breaker timeout

[sentigent.webhooks]
# Fire webhooks on events — multiple URLs per event type
escalation = ["https://hooks.slack.com/...", "https://pagerduty.com/..."]
outcome = []
pattern_discovered = []

[sentigent.thresholds]
# Override per-profile thresholds
caution = 0.45
doubt = 0.40
urgency = 0.55
confidence = 0.65
`} />
      <H2>Profile Customization</H2>
      <CodeBlock lang="python" code={`
from sentigent.core.types import Profile

custom_profile = Profile(
    name="my_custom",
    caution_threshold=0.40,
    doubt_threshold=0.35,
    urgency_threshold=0.60,
    confidence_threshold=0.70,
    signal_weights={"caution": 1.5, "confidence": 0.8},
    escalation_keywords=["production", "billing", "delete"],
)

judge = Sentigent(profile=custom_profile)
`} />
      <H2>Webhook Events</H2>
      <Table
        head={["Event", "When fired"]}
        rows={[
          ["escalation", "Decision is escalate"],
          ["outcome", "record_outcome() called"],
          ["pattern_discovered", "New procedural rule mined"],
          ["circuit_breaker", "Memory circuit open/close"],
          ["judgment_milestone", "Score crosses 10% improvement threshold"],
          ["drift_detected", "Baseline drift detected"],
        ]}
      />
      <H2>Webhook Payload</H2>
      <CodeBlock lang="json" code={`
{
  "event_type": "escalation",
  "timestamp": "2024-01-15T10:23:45Z",
  "trace_id": "abc-123",
  "agent_id": "my-agent",
  "action": "escalate",
  "reason": "No-force-push policy matched",
  "signals": { "caution": 0.9, "doubt": 0.2 },
  "context": { "tool_name": "Bash", "task": "git push --force" },
  "metadata": {}
}
`} />
    </div>
  );
}

function ProveSection() {
  return (
    <div>
      <H2>What Is Proof of Value?</H2>
      <P>The <strong className="text-white/80">/prove</strong> command (and Proof of Value dashboard page) generates a quantified report showing what Sentigent has actually prevented, caught, and improved — making the ROI visible to stakeholders.</P>
      <H2>Key Metrics</H2>
      <Table
        head={["Metric", "Description"]}
        rows={[
          ["confirmed_catches", "Decisions rated escalate/slow_down with outcome=correct. These are real interventions that mattered."],
          ["intervention_accuracy", "% of non-proceed decisions that were correct. 80%+ is excellent."],
          ["false_negatives", "Decisions rated proceed with outcome=incorrect. Missed catches."],
          ["safe_passes", "Decisions rated proceed with outcome=correct. Benign cases correctly allowed."],
          ["total_policy_enforcements", "Total times a policy fired across all agents in the org."],
        ]}
      />
      <H2>Score Trajectory</H2>
      <P>Shows judgment accuracy over rolling time windows (last 7d, 30d, 90d). A rising trajectory means Sentigent is learning. A flat trajectory means it needs more outcome data.</P>
      <H2>Top Catches</H2>
      <P>The most significant escalations/slow_downs that were later confirmed correct. These are your highest-value interventions — the ones where Sentigent prevented something bad.</P>
      <H2>CLI Usage</H2>
      <CodeBlock lang="bash" code={`
# Full proof report
sentigent prove

# Via MCP tool
sentigent_prove()

# Via API
GET /api/prove
`} />
      <H2>Interpreting the Verdict</H2>
      <Table
        head={["Verdict", "What it means"]}
        rows={[
          ["🟢 Strong proof", "High accuracy + multiple confirmed catches + rising trajectory."],
          ["🟡 Emerging proof", "Good accuracy but few outcome ratings. Record more outcomes."],
          ["🔴 Needs calibration", "Low accuracy or falling trajectory. Consider profile adjustment."],
        ]}
      />
      <Callout type="tip">
        <strong>Most important action:</strong> Record outcomes consistently with{" "}
        <code className="font-mono text-xs">sentigent_outcome(trace_id, 'correct'/'incorrect')</code> after
        every significant decision. Without outcomes, Sentigent cannot learn or generate meaningful proof.
      </Callout>
    </div>
  );
}

const SECTION_CONTENT: Record<SectionId, () => React.ReactElement> = {
  overview: OverviewSection,
  quickstart: QuickStartSection,
  concepts: ConceptsSection,
  intelligence: IntelligenceSection,
  policies: PoliciesSection,
  collective: CollectiveSection,
  api: ApiSection,
  mcp: McpSection,
  config: ConfigSection,
  prove: ProveSection,
};

// ── Main page ─────────────────────────────────────────────────────────────────

export function Help() {
  const [active, setActive] = useState<SectionId>("overview");
  const Content = SECTION_CONTENT[active];

  return (
    <div className="flex h-full min-h-0">
      {/* Sidebar nav */}
      <aside className="w-[200px] shrink-0 border-r border-bg-border/50 py-4 overflow-y-auto"
        style={{ background: "rgba(7,9,15,0.6)" }}>
        <p className="px-4 text-[10px] font-semibold text-muted/40 uppercase tracking-widest mb-3">
          Documentation
        </p>
        <div className="space-y-0.5 px-2">
          {SECTIONS.map(s => {
            const isActive = s.id === active;
            return (
              <button
                key={s.id}
                onClick={() => setActive(s.id)}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-left transition-all ${
                  isActive ? "text-white" : "text-muted/60 hover:text-white/80"
                }`}
                style={isActive ? {
                  background: "linear-gradient(90deg, rgba(124,58,237,0.18), rgba(124,58,237,0.06))",
                  borderLeft: "2px solid #7c3aed",
                  paddingLeft: "calc(0.75rem - 2px)",
                } : {}}
              >
                <span className={`flex-shrink-0 ${isActive ? "text-accent-light" : "text-muted/50"}`}>
                  {s.icon}
                </span>
                <span className="font-medium text-[13px]">{s.label}</span>
              </button>
            );
          })}
        </div>
      </aside>

      {/* Content */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-3xl px-8 py-6">
          {/* Section header */}
          <div className="mb-6 pb-4 border-b border-bg-border/40">
            <div className="flex items-center gap-2 text-accent-light mb-1">
              {SECTIONS.find(s => s.id === active)?.icon}
              <span className="text-[11px] font-semibold uppercase tracking-widest text-muted/50">
                Sentigent Docs
              </span>
            </div>
            <h1 className="text-xl font-bold text-white">
              {SECTIONS.find(s => s.id === active)?.label}
            </h1>
          </div>

          {/* Section content */}
          <Content />

          {/* Footer nav */}
          <div className="flex justify-between mt-10 pt-5 border-t border-bg-border/40">
            {(() => {
              const idx = SECTIONS.findIndex(s => s.id === active);
              const prev = SECTIONS[idx - 1];
              const next = SECTIONS[idx + 1];
              return (
                <>
                  {prev ? (
                    <button onClick={() => setActive(prev.id)}
                      className="flex items-center gap-2 text-sm text-muted/50 hover:text-white transition-colors">
                      ← {prev.label}
                    </button>
                  ) : <div />}
                  {next ? (
                    <button onClick={() => setActive(next.id)}
                      className="flex items-center gap-2 text-sm text-muted/50 hover:text-white transition-colors">
                      {next.label} →
                    </button>
                  ) : <div />}
                </>
              );
            })()}
          </div>
        </div>
      </main>
    </div>
  );
}
