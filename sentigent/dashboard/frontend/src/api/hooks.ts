import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { OrgPolicy } from "@/types";

// ── Query Keys ─────────────────────────────────────────────

export const keys = {
  score: ["score"] as const,
  sprint: ["sprint"] as const,
  timeline: ["timeline"] as const,
  insights: ["insights"] as const,
  episodes: (limit: number, search: string) => ["episodes", limit, search] as const,
  patterns: ["patterns"] as const,
  baselines: ["baselines"] as const,
  layer2Status: ["layer2", "status"] as const,
  layer2Org: ["layer2", "org"] as const,
  layer2Timeline: ["layer2", "timeline"] as const,
  policies: ["policies"] as const,
  practiceTemplates: ["practice-templates"] as const,
  prove: (days: number) => ["prove", days] as const,
  collective: (orgId: string) => ["collective", orgId] as const,
  collectivePatterns: (orgId: string) => ["collective-patterns", orgId] as const,
  templates: ["prompt-builder", "templates"] as const,
};

// ── Local Agent ─────────────────────────────────────────────

export function useScore() {
  return useQuery({ queryKey: keys.score, queryFn: api.getScore, refetchInterval: 30_000 });
}

export function useSprint() {
  return useQuery({ queryKey: keys.sprint, queryFn: api.getSprint, refetchInterval: 60_000 });
}

export function useTimeline() {
  return useQuery({ queryKey: keys.timeline, queryFn: api.getTimeline, refetchInterval: 60_000 });
}

export function useInsights() {
  return useQuery({ queryKey: keys.insights, queryFn: api.getInsights, refetchInterval: 60_000 });
}

export function useEpisodes(limit = 50, search = "") {
  return useQuery({
    queryKey: keys.episodes(limit, search),
    queryFn: () => api.getEpisodes(limit, search),
    refetchInterval: 15_000,
  });
}

export function usePatterns() {
  return useQuery({ queryKey: keys.patterns, queryFn: api.getPatterns, refetchInterval: 60_000 });
}

export function useBaselines() {
  return useQuery({ queryKey: keys.baselines, queryFn: api.getBaselines, refetchInterval: 60_000 });
}

// ── Layer 2 ────────────────────────────────────────────────

export function useLayer2Status() {
  return useQuery({ queryKey: keys.layer2Status, queryFn: api.getLayer2Status });
}

export function useLayer2Org() {
  return useQuery({
    queryKey: keys.layer2Org,
    queryFn: api.getLayer2Org,
    refetchInterval: 30_000,
    retry: 1,
  });
}

export function useLayer2Timeline() {
  return useQuery({
    queryKey: keys.layer2Timeline,
    queryFn: api.getLayer2Timeline,
    refetchInterval: 60_000,
    retry: 1,
  });
}

// ── Policies ───────────────────────────────────────────────

export function usePolicies() {
  return useQuery({ queryKey: keys.policies, queryFn: api.getPolicies, refetchInterval: 30_000 });
}

export function usePracticeTemplates() {
  return useQuery({ queryKey: keys.practiceTemplates, queryFn: api.getPracticeTemplates });
}

export function useCreatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (policy: Omit<OrgPolicy, "trigger_count" | "last_triggered">) =>
      api.createPolicy(policy),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.policies }),
  });
}

export function useUpdatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, updates }: { name: string; updates: Partial<OrgPolicy> }) =>
      api.updatePolicy(name, updates),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.policies }),
  });
}

export function useTogglePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.togglePolicy(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.policies }),
  });
}

// ── Proof of Value ─────────────────────────────────────────

export function useProve(days = 90) {
  return useQuery({
    queryKey: keys.prove(days),
    queryFn: () => api.getProve(days),
    refetchInterval: 60_000,
  });
}

// ── Collective Intelligence ────────────────────────────────

export function useCollective(orgId = "") {
  return useQuery({
    queryKey: keys.collective(orgId),
    queryFn: () => api.getCollective(orgId),
    refetchInterval: 120_000,
  });
}

export function useCollectivePatterns(orgId = "") {
  return useQuery({
    queryKey: keys.collectivePatterns(orgId),
    queryFn: () => api.getCollectivePatterns(orgId),
  });
}

// ── Prompt Builder ─────────────────────────────────────────

export function usePromptTemplates() {
  return useQuery({ queryKey: keys.templates, queryFn: api.getTemplates });
}
