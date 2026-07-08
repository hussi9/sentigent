// ── Core Decision Types ─────────────────────────────────────

export type DecisionAction = "proceed" | "slow_down" | "enrich" | "escalate";

export type SignalType = "caution" | "doubt" | "urgency" | "confidence" | "frustration";

export type Severity = "low" | "medium" | "high" | "critical";

export interface Signal {
  type: SignalType;
  strength: number;
  reason: string;
  contributing_factors: string[];
}

export interface Episode {
  trace_id: string;
  task: string;
  decision: DecisionAction;
  outcome: "correct" | "incorrect" | "neutral" | null;
  confidence_at_decision: number;
  signals: Record<string, number>;
  timestamp: string;
  reason: string;
  agent_id?: string;
  tool_name?: string;
  policy_name?: string;
}

// ── Scoring & Analytics ────────────────────────────────────

export interface ScoreResponse {
  score: number;
  score_pct: string;
  total_episodes: number;
  total_with_outcomes: number;
  outcomes: {
    correct: number;
    incorrect: number;
    neutral?: number;
  };
}

export interface TimelinePoint {
  day: string;
  total: number;
  correct: number;
  score: number;
}

export interface Pattern {
  pattern_name: string;
  learned_action: DecisionAction;
  success_rate: number;
  sample_size: number;
  last_reinforced: string | null;
}

export interface Baseline {
  metric: string;
  median: number;
  std: number;
  p5: number;
  p95: number;
  sample_size: number;
  source: string;
  last_updated: string;
}

export interface Insight {
  category: "correlation" | "trend" | "anomaly" | "metric";
  subject: string;
  finding: string;
  confidence: number;
  recommendation?: string;
  signal_weight?: number;
  computed_at?: string;
}

export interface InsightsResponse {
  correlations: Insight[];
  trends: Insight[];
  anomalies: Insight[];
  brier_score: number | null;
  brier_interpretation: string;
  recommendations: string[];
  computed_at: string | null;
}

// ── Org Layer (Layer 2) ────────────────────────────────────

export interface AgentStats {
  agent_id: string;
  total_episodes: number;
  correct: number;
  incorrect: number;
  neutral: number;
  score: number;
  score_pct: string;
}

export interface OrgOverview {
  org_score: number;
  org_score_pct: string;
  total_episodes: number;
  total_agents: number;
  agents: AgentStats[];
  patterns: Pattern[];
  baselines: Baseline[];
}

// ── Policies ───────────────────────────────────────────────

export interface OrgPolicy {
  policy_name: string;
  org_id?: string;
  trigger_tool: "Bash" | "Write" | "Edit" | "*";
  trigger_pattern: string;
  profile_override: string;
  enforce_action: "block" | "escalate" | "slow_down" | "enrich";
  enforce_reason: string;
  severity: Severity;
  is_active: boolean;
  trigger_count?: number;
  last_triggered?: string | null;
}

export interface PolicyViolation {
  policy_name: string;
  agent_id: string;
  enforced_action: string;
  task?: string;
  timestamp: string;
}

export interface PoliciesResponse {
  policies: OrgPolicy[];
  recent_violations: PolicyViolation[];
  total_policies: number;
}

export interface PracticeTemplate {
  id: string;
  name: string;
  description: string;
  category: "testing" | "security" | "quality" | "process" | "safety";
  policy: Omit<OrgPolicy, "org_id" | "is_active" | "trigger_count" | "last_triggered">;
}

// ── Collective Intelligence (Layer 3) ─────────────────────

export interface Layer3Pattern {
  pattern_name: string;
  learned_action: DecisionAction;
  success_rate: number;
  sample_size: number;
  contributing_org_count: number;
  industry_tags: string[];
}

export interface CollectiveStats {
  pool_size: number;
  pool_avg_success_rate: number;
  multi_org_patterns: number;
  opted_in_profiles: string[];
}

export interface CollectiveResponse {
  status: string;
  collective?: CollectiveStats;
  patterns?: Layer3Pattern[];
  opted_in?: boolean;
  profile?: string;
}

// ── Proof of Value ─────────────────────────────────────────

export interface TopCatch {
  timestamp: string;
  decision: DecisionAction;
  task: string;
  reason: string;
  confidence: number;
  policy_name?: string;
  tool?: string;
}

export interface PolicyStat {
  policy_name: string;
  enforce_action: string;
  severity: Severity;
  trigger_count: number;
}

export interface ProveResponse {
  confirmed_catches: number;
  intervention_accuracy: number;
  false_negatives: number;
  safe_passes: number;
  total_policy_enforcements: number;
  score_trajectory: Array<{ period: string; score: number; total_rated: number }>;
  top_catches: TopCatch[];
  policy_stats: PolicyStat[];
  agent_compliance: Array<{ agent_id: string; score: number; total_episodes: number; policy_hits: number }>;
  verdict: string;
}

// ── Prompt Builder ─────────────────────────────────────────

export type TemplateName =
  | "product_spec"
  | "pr_review"
  | "bug_report"
  | "code_refactor"
  | "architecture_decision"
  | "api_design"
  | "task_breakdown";

export interface TemplateInfo {
  name: TemplateName;
  description: string;
  fields: number;
  required_fields: number;
  skill: string;
}

export interface PromptSession {
  session_id: string;
  status: "in_progress" | "complete" | "needs_answer";
  template?: string;
  field?: string;
  question?: string;
  placeholder?: string;
  hint?: string;
  example?: string;
  required?: boolean;
  progress?: string;
  answered?: string;
  prompt?: string;
  field_count?: number;
  skill_to_invoke?: string;
  error?: string;
}

// ── Real-time / SSE ────────────────────────────────────────

export interface LiveDecision {
  type: "decision";
  trace_id: string;
  agent_id: string;
  task: string;
  action: DecisionAction;
  confidence: number;
  timestamp: string;
}

// ── Navigation ─────────────────────────────────────────────

export type NavPage =
  | "intelligence"
  | "dashboard"
  | "agents"
  | "policies"
  | "prompt-builder"
  | "collective"
  | "proof"
  | "onboarding"
  | "my-agent"
  | "admin/layer1"
  | "settings/org"
  | "settings/members"
  | "org-knowledge"
  | "help";

// ── Layer 2 Status ─────────────────────────────────────────

export interface Layer2Status {
  configured: boolean;
  supabase_url: string | null;
  org_id: string;
}

// ── Truth Sprint (WS-B ablation harness) ───────────────────

export interface SprintArm {
  n: number;
  resolved: number;
  vacr: number | null;
}

export interface SprintResponse {
  wsb_status: string;
  wsb_slices: string[];
  assumptions: { id: string; claim: string }[];
  assumptions_passed: number;
  assumptions_total: number;
  assumptions_test: string;
  grader: {
    total: number;
    correct: number;
    incorrect: number;
    repaired: number;
    incorrect_rate: number;
    repair_success_rate: number;
  };
  ablation: { a0: SprintArm | null; a1: SprintArm | null; a2: SprintArm | null };
  ablation_total_rows: number;
  has_real_pilot: boolean;
  verdict: string;
  metered_cost_usd: number;
}
