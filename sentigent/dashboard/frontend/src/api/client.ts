import type {
  ScoreResponse,
  Episode,
  Pattern,
  Baseline,
  InsightsResponse,
  TimelinePoint,
  OrgOverview,
  Layer2Status,
  PoliciesResponse,
  OrgPolicy,
  CollectiveResponse,
  ProveResponse,
  TemplateInfo,
  PromptSession,
  SprintResponse,
  Practice,
  PracticesResponse,
  PracticeEnforcement,
  EscalationsResponse,
  EscalationDecision,
  RoutingSeedsResponse,
  RoutingReconcileResult,
} from "@/types";

const BASE = "/api";

async function get<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)));
  }
  const res = await fetch(url.toString());
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || res.statusText);
  }
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function patch<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// ── Local Agent ─────────────────────────────────────────────

export const api = {
  // Score & overview
  getScore: () => get<ScoreResponse>("/score"),
  getTimeline: () => get<TimelinePoint[]>("/timeline"),
  getInsights: () => get<InsightsResponse>("/insights"),

  // Truth sprint (WS-B ablation harness)
  getSprint: () => get<SprintResponse>("/sprint"),

  // Episodes
  getEpisodes: (limit = 50, search = "") =>
    get<Episode[]>("/episodes", { limit, ...(search ? { search } : {}) }),

  // Patterns & baselines
  getPatterns: () => get<Pattern[]>("/patterns"),
  getBaselines: () => get<Baseline[]>("/baselines"),

  // Layer 2
  getLayer2Status: () => get<Layer2Status>("/layer2/status"),
  getLayer2Org: () => get<OrgOverview>("/layer2/org"),
  getLayer2Timeline: () => get<TimelinePoint[]>("/layer2/timeline"),

  // Policies
  getPolicies: () => get<PoliciesResponse>("/policies"),
  createPolicy: (policy: Omit<OrgPolicy, "trigger_count" | "last_triggered">) =>
    post<{ status: string; message: string }>("/policies", policy),
  updatePolicy: (name: string, updates: Partial<OrgPolicy>) =>
    put<{ status: string; message: string }>(`/policies/${encodeURIComponent(name)}`, updates),
  togglePolicy: (name: string) =>
    patch<{ status: string; is_active: boolean }>(`/policies/${encodeURIComponent(name)}/toggle`),
  deletePolicy: (name: string) =>
    patch<{ status: string; message: string }>(`/policies/${encodeURIComponent(name)}/deactivate`),
  getPracticeTemplates: () => get<{ templates: import("@/types").PracticeTemplate[] }>("/practice-templates"),

  // Proof of value
  getProve: (days = 90) => get<ProveResponse>("/prove", { days }),

  // Collective (Layer 3)
  getCollective: (orgId = "") =>
    get<CollectiveResponse>("/collective", { ...(orgId ? { org_id: orgId } : {}), action: "status" }),
  getCollectivePatterns: (orgId = "") =>
    get<CollectiveResponse>("/collective", { ...(orgId ? { org_id: orgId } : {}), action: "pull" }),

  // Practices
  getPractices: () => get<PracticesResponse>("/practices"),
  createPractice: (practice: { text: string; domain?: string; cadence?: string }) =>
    post<Practice>("/practices", practice),
  setPracticeEnforcement: (id: number, level: PracticeEnforcement) =>
    post<Practice>(`/practices/${id}/enforcement`, { level }),
  togglePractice: (id: number) =>
    post<Practice>(`/practices/${id}/toggle`, undefined),

  // Escalations
  getEscalations: () => get<EscalationsResponse>("/escalations"),
  answerEscalation: (loopId: string, decision: EscalationDecision) =>
    post<{ status: string; [key: string]: unknown }>(`/escalations/${encodeURIComponent(loopId)}/answer`, { decision }),

  // Routing seeds
  getRoutingSeeds: () => get<RoutingSeedsResponse>("/routing/seeds"),
  reconcileRouting: (dryRun: boolean) =>
    post<RoutingReconcileResult>("/routing/reconcile", { dry_run: dryRun }),

  // Prompt builder
  getTemplates: () => get<TemplateInfo[]>("/prompt-builder/templates"),
  startSession: (template: string) =>
    post<PromptSession>("/prompt-builder/start", { template }),
  answerField: (sessionId: string, answer: string) =>
    post<PromptSession>("/prompt-builder/answer", { session_id: sessionId, answer }),
  skipField: (sessionId: string) =>
    post<PromptSession>("/prompt-builder/skip", { session_id: sessionId }),
  abandonSession: (sessionId: string) =>
    post<PromptSession>("/prompt-builder/abandon", { session_id: sessionId }),
};

// ── SSE — Live Decision Stream ──────────────────────────────

export function subscribeToDecisions(
  onDecision: (d: import("@/types").LiveDecision) => void,
  onError?: (e: Event) => void,
): () => void {
  const source = new EventSource("/api/decisions/stream");

  source.addEventListener("decision", (e) => {
    try {
      onDecision(JSON.parse((e as MessageEvent).data));
    } catch {
      // ignore parse errors
    }
  });

  if (onError) source.onerror = onError;

  return () => source.close();
}
