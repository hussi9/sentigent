import { useState } from "react";
import { toast } from "sonner";
import {
  ShieldCheck, Plus, ToggleLeft, ToggleRight, AlertTriangle, Loader2, X, ChevronDown, ChevronUp, Bookmark,
} from "lucide-react";
import { usePolicies, usePracticeTemplates, useCreatePolicy, useTogglePolicy } from "@/api/hooks";
import {
  Card, CardHeader, CardTitle, CardBody, StatCard, SeverityBadge, ActionBadge, Badge,
} from "@/components/ui";
import type { OrgPolicy, PracticeTemplate } from "@/types";

function formatTime(ts: string | null | undefined) {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

interface PolicyFormState {
  policy_name: string;
  trigger_tool: OrgPolicy["trigger_tool"];
  trigger_pattern: string;
  enforce_action: OrgPolicy["enforce_action"];
  enforce_reason: string;
  severity: OrgPolicy["severity"];
  profile_override: string;
  is_active: boolean;
}

const BLANK_FORM: PolicyFormState = {
  policy_name: "",
  trigger_tool: "*",
  trigger_pattern: "",
  enforce_action: "slow_down",
  enforce_reason: "",
  severity: "medium",
  profile_override: "",
  is_active: true,
};

function PolicyForm({ onSubmit, onClose, initial = BLANK_FORM }: {
  onSubmit: (p: PolicyFormState) => void;
  onClose: () => void;
  initial?: PolicyFormState;
}) {
  const [form, setForm] = useState<PolicyFormState>(initial);
  const set = (k: keyof PolicyFormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const inputCls = "input w-full";
  const labelCls = "text-[11px] font-semibold text-muted uppercase tracking-wider mb-1.5 block";

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-md flex items-center justify-center z-50 animate-fade-in">
      <div className="bg-bg-surface border border-bg-border rounded-2xl w-full max-w-lg shadow-glow mx-4">
        <div className="flex items-center justify-between px-5 py-4 border-b border-bg-border"
          style={{ background: "rgba(20,27,38,0.6)" }}>
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-accent/15 flex items-center justify-center">
              <ShieldCheck size={12} className="text-accent-light" />
            </div>
            <h3 className="text-sm font-semibold text-white">New Policy Rule</h3>
          </div>
          <button onClick={onClose} className="btn btn-ghost p-1 rounded-md">
            <X size={15} />
          </button>
        </div>
        <div className="px-5 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
          <div>
            <label className={labelCls}>Policy Name *</label>
            <input className={inputCls} placeholder="e.g. no_force_push" value={form.policy_name} onChange={set("policy_name")} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Trigger Tool</label>
              <select className={inputCls} value={form.trigger_tool} onChange={set("trigger_tool")}>
                <option value="*">Any tool (*)</option>
                <option value="Bash">Bash</option>
                <option value="Write">Write</option>
                <option value="Edit">Edit</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Enforce Action</label>
              <select className={inputCls} value={form.enforce_action} onChange={set("enforce_action")}>
                <option value="slow_down">Slow Down</option>
                <option value="escalate">Escalate</option>
                <option value="enrich">Enrich</option>
                <option value="block">Block</option>
              </select>
            </div>
          </div>
          <div>
            <label className={labelCls}>Trigger Pattern (regex)</label>
            <input className={inputCls} placeholder="e.g. push.*--force|reset.*--hard" value={form.trigger_pattern} onChange={set("trigger_pattern")} />
          </div>
          <div>
            <label className={labelCls}>Reason / Description</label>
            <textarea className={inputCls} rows={2} placeholder="Why is this policy needed?" value={form.enforce_reason} onChange={set("enforce_reason")} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Severity</label>
              <select className={inputCls} value={form.severity} onChange={set("severity")}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Profile Scope (optional)</label>
              <input className={inputCls} placeholder="e.g. security (blank = all)" value={form.profile_override} onChange={set("profile_override")} />
            </div>
          </div>
        </div>
        <div className="flex gap-2 px-5 py-4 border-t border-bg-border">
          <button
            onClick={() => onSubmit(form)}
            disabled={!form.policy_name}
            className="btn btn-primary flex-1 py-2 disabled:opacity-40 disabled:cursor-not-allowed disabled:transform-none"
          >
            Create Policy
          </button>
          <button onClick={onClose} className="btn btn-ghost px-4 py-2 border border-bg-border">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function PracticeTemplateCard({ template, onApply }: { template: PracticeTemplate; onApply: (t: PracticeTemplate) => void }) {
  const CATEGORY_COLORS: Record<string, string> = {
    testing: "info", security: "danger", quality: "accent", process: "warning", safety: "danger",
  };

  return (
    <div className="p-4 rounded-lg bg-bg-elevated border border-bg-border hover:border-accent/30 transition-colors">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <div className="text-xs font-semibold text-white">{template.name}</div>
          <Badge variant={CATEGORY_COLORS[template.category] as "info" | "danger" | "accent" | "warning"} size="sm" >
            {template.category}
          </Badge>
        </div>
        <button
          onClick={() => onApply(template)}
          className="shrink-0 px-2.5 py-1 text-[11px] font-medium bg-accent/15 hover:bg-accent/25 text-accent-light border border-accent/25 rounded-md transition-colors"
        >
          Apply
        </button>
      </div>
      <p className="text-[11px] text-muted">{template.description}</p>
      <div className="mt-2 flex items-center gap-2 text-[10px] text-muted">
        <span className="font-mono">{template.policy.trigger_tool}</span>
        <span>·</span>
        <ActionBadge action={template.policy.enforce_action} />
        <span>·</span>
        <SeverityBadge severity={template.policy.severity} />
      </div>
    </div>
  );
}

export function PolicyManager() {
  const [showForm, setShowForm] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [formInitial, setFormInitial] = useState<PolicyFormState>(BLANK_FORM);

  const { data: policiesData, isLoading } = usePolicies();
  const { data: templatesData } = usePracticeTemplates();
  const createPolicy = useCreatePolicy();
  const togglePolicy = useTogglePolicy();

  const policies = policiesData?.policies ?? [];
  const violations = policiesData?.recent_violations ?? [];
  const templates = templatesData?.templates ?? [];

  const activePolicies = policies.filter((p) => p.is_active);
  const criticalPolicies = policies.filter((p) => p.severity === "critical" && p.is_active);
  const totalTriggers = policies.reduce((s, p) => s + (p.trigger_count ?? 0), 0);

  function handleCreate(form: PolicyFormState) {
    createPolicy.mutate(form, {
      onSuccess: () => {
        setShowForm(false);
        toast.success(`Policy "${form.policy_name}" created`, {
          description: `Action: ${form.enforce_action} · Severity: ${form.severity}`,
        });
      },
      onError: () => toast.error("Failed to create policy"),
    });
  }

  function handleApplyTemplate(t: PracticeTemplate) {
    setFormInitial({
      policy_name: t.policy.policy_name,
      trigger_tool: t.policy.trigger_tool,
      trigger_pattern: t.policy.trigger_pattern,
      enforce_action: t.policy.enforce_action,
      enforce_reason: t.policy.enforce_reason,
      severity: t.policy.severity,
      profile_override: t.policy.profile_override,
      is_active: true,
    });
    setShowTemplates(false);
    setShowForm(true);
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      {showForm && (
        <PolicyForm
          onSubmit={handleCreate}
          onClose={() => setShowForm(false)}
          initial={formInitial}
        />
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Active Policies" value={activePolicies.length} color="accent" icon={<ShieldCheck size={14} />} />
        <StatCard label="Critical Rules" value={criticalPolicies.length} color={criticalPolicies.length > 0 ? "danger" : "default"} icon={<AlertTriangle size={14} />} />
        <StatCard label="Total Triggers" value={totalTriggers} sub="all time" />
        <StatCard label="Recent Violations" value={violations.length} color={violations.length > 0 ? "warning" : "default"} />
      </div>

      {/* Practice Templates */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Bookmark size={14} />}>Development Practice Templates</CardTitle>
          <button
            onClick={() => setShowTemplates((v) => !v)}
            className="flex items-center gap-1 text-xs text-accent-light hover:text-accent transition-colors"
          >
            {showTemplates ? "Hide" : "Browse templates"}
            {showTemplates ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        </CardHeader>
        {showTemplates && (
          <CardBody>
            <p className="text-xs text-muted mb-4">
              Pre-built policies for common engineering best practices. Click "Apply" to pre-fill the policy form.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {templates.map((t) => (
                <PracticeTemplateCard key={t.id} template={t} onApply={handleApplyTemplate} />
              ))}
              {!templates.length && (
                <p className="text-xs text-muted col-span-3">Loading templates…</p>
              )}
            </div>
          </CardBody>
        )}
      </Card>

      {/* Active Policies */}
      <Card>
        <CardHeader>
          <CardTitle icon={<ShieldCheck size={14} />}>Org Policies</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="muted">{policies.length} total</Badge>
            <button
              onClick={() => { setFormInitial(BLANK_FORM); setShowForm(true); }}
              className="btn btn-primary"
            >
              <Plus size={12} />
              New Policy
            </button>
          </div>
        </CardHeader>
        <div className="overflow-x-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={16} className="animate-spin text-muted" />
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-bg-border">
                  {["Status", "Policy", "Tool", "Pattern", "Action", "Severity", "Triggers", "Last Hit"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left text-muted font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {policies.map((p) => (
                  <tr key={p.policy_name} className="border-b border-bg-border/50 hover:bg-bg-hover transition-colors">
                    <td className="px-4 py-2.5">
                      <button
                        onClick={() => togglePolicy.mutate(p.policy_name, {
                          onSuccess: () => toast.success(`Policy ${p.is_active ? "disabled" : "enabled"}`, { description: p.policy_name }),
                          onError: () => toast.error("Failed to update policy"),
                        })}
                        className="text-muted hover:text-white transition-colors"
                        title={p.is_active ? "Disable policy" : "Enable policy"}
                      >
                        {p.is_active
                          ? <ToggleRight size={18} className="text-success" />
                          : <ToggleLeft size={18} className="text-muted" />
                        }
                      </button>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="font-mono text-white/80">{p.policy_name}</div>
                      {p.enforce_reason && (
                        <div className="text-[10px] text-muted truncate max-w-xs" title={p.enforce_reason}>
                          {p.enforce_reason}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-muted">{p.trigger_tool}</td>
                    <td className="px-4 py-2.5 font-mono text-muted max-w-xs truncate" title={p.trigger_pattern}>
                      {p.trigger_pattern || <span className="text-muted/40 italic">any</span>}
                    </td>
                    <td className="px-4 py-2.5"><ActionBadge action={p.enforce_action} /></td>
                    <td className="px-4 py-2.5"><SeverityBadge severity={p.severity} /></td>
                    <td className="px-4 py-2.5 text-white/80">{p.trigger_count ?? 0}</td>
                    <td className="px-4 py-2.5 text-muted">{formatTime(p.last_triggered)}</td>
                  </tr>
                ))}
                {!policies.length && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-muted">
                      No policies yet — create your first policy or apply a practice template.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      {/* Recent Violations */}
      {violations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle icon={<AlertTriangle size={14} />}>Recent Violations</CardTitle>
            <Badge variant="warning">{violations.length}</Badge>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-bg-border">
                  {["Time", "Agent", "Policy", "Action Taken", "Task"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left text-muted font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {violations.map((v, i) => (
                  <tr key={i} className="border-b border-bg-border/50 hover:bg-bg-hover transition-colors">
                    <td className="px-4 py-2.5 text-muted font-mono whitespace-nowrap">
                      {formatTime(v.timestamp)}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-accent-light">{v.agent_id}</td>
                    <td className="px-4 py-2.5 font-mono text-white/80">{v.policy_name}</td>
                    <td className="px-4 py-2.5"><ActionBadge action={v.enforced_action} /></td>
                    <td className="px-4 py-2.5 text-muted max-w-xs truncate" title={v.task}>
                      {v.task ? v.task.slice(0, 60) + (v.task.length > 60 ? "…" : "") : "—"}
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
