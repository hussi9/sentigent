import { useState } from "react";
import { toast } from "sonner";
import { ClipboardList, Plus, ToggleLeft, ToggleRight, Loader2, X } from "lucide-react";
import {
  usePractices, useCreatePractice, useSetPracticeEnforcement, useTogglePractice,
} from "@/api/hooks";
import {
  Card, CardHeader, CardTitle, StatCard, Badge, EmptyState,
} from "@/components/ui";
import type { Practice, PracticeEnforcement } from "@/types";

const ENFORCEMENT_LEVELS: PracticeEnforcement[] = ["off", "warn", "block"];

interface PracticeFormState {
  text: string;
  domain: string;
  cadence: string;
}

const BLANK_FORM: PracticeFormState = { text: "", domain: "global", cadence: "always" };

function PracticeForm({ onSubmit, onClose }: {
  onSubmit: (p: PracticeFormState) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<PracticeFormState>(BLANK_FORM);
  const set = (k: keyof PracticeFormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
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
              <ClipboardList size={12} className="text-accent-light" />
            </div>
            <h3 className="text-sm font-semibold text-white">New Practice</h3>
          </div>
          <button onClick={onClose} className="btn btn-ghost p-1 rounded-md">
            <X size={15} />
          </button>
        </div>
        <div className="px-5 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
          <div>
            <label className={labelCls}>Practice *</label>
            <textarea className={inputCls} rows={2} placeholder="e.g. Write tests before implementation" value={form.text} onChange={set("text")} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Domain</label>
              <input className={inputCls} placeholder="e.g. global" value={form.domain} onChange={set("domain")} />
            </div>
            <div>
              <label className={labelCls}>Cadence</label>
              <input className={inputCls} placeholder="e.g. always" value={form.cadence} onChange={set("cadence")} />
            </div>
          </div>
        </div>
        <div className="flex gap-2 px-5 py-4 border-t border-bg-border">
          <button
            onClick={() => onSubmit(form)}
            disabled={!form.text.trim()}
            className="btn btn-primary flex-1 py-2 disabled:opacity-40 disabled:cursor-not-allowed disabled:transform-none"
          >
            Create Practice
          </button>
          <button onClick={onClose} className="btn btn-ghost px-4 py-2 border border-bg-border">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function EnforcementControl({ practice, onChange }: {
  practice: Practice;
  onChange: (level: PracticeEnforcement) => void;
}) {
  return (
    <div className="inline-flex rounded-lg border border-bg-border overflow-hidden">
      {ENFORCEMENT_LEVELS.map((level) => {
        const active = practice.enforcement === level;
        return (
          <button
            key={level}
            onClick={() => onChange(level)}
            className={`px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider transition-colors ${
              active
                ? level === "block" ? "bg-danger/20 text-danger-light" : level === "warn" ? "bg-warning/20 text-warning-light" : "bg-bg-elevated text-muted"
                : "text-muted/50 hover:text-muted hover:bg-bg-hover"
            }`}
          >
            {level}
          </button>
        );
      })}
    </div>
  );
}

export function Practices() {
  const [showForm, setShowForm] = useState(false);
  const { data, isLoading } = usePractices();
  const createPractice = useCreatePractice();
  const setEnforcement = useSetPracticeEnforcement();
  const togglePractice = useTogglePractice();

  const practices = data?.practices ?? [];
  const activeCount = practices.filter((p) => p.active).length;
  const blockCount = practices.filter((p) => p.enforcement === "block" && p.active).length;
  const totalFollowed = practices.reduce((s, p) => s + (p.times_followed ?? 0), 0);
  const totalSkipped = practices.reduce((s, p) => s + (p.times_skipped ?? 0), 0);

  function handleCreate(form: PracticeFormState) {
    createPractice.mutate(
      { text: form.text.trim(), domain: form.domain.trim() || "global", cadence: form.cadence.trim() || "always" },
      {
        onSuccess: () => {
          setShowForm(false);
          toast.success("Practice added", { description: form.text.trim() });
        },
        onError: () => toast.error("Failed to add practice"),
      },
    );
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      {showForm && (
        <PracticeForm onSubmit={handleCreate} onClose={() => setShowForm(false)} />
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Active Practices" value={activeCount} color="accent" icon={<ClipboardList size={14} />} />
        <StatCard label="Enforced (block)" value={blockCount} color={blockCount > 0 ? "danger" : "default"} />
        <StatCard label="Times Followed" value={totalFollowed} color="success" />
        <StatCard label="Times Skipped" value={totalSkipped} color={totalSkipped > 0 ? "warning" : "default"} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle icon={<ClipboardList size={14} />}>Declared Practices</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="muted">{practices.length} total</Badge>
            <button
              onClick={() => setShowForm(true)}
              className="btn btn-primary"
            >
              <Plus size={12} />
              New Practice
            </button>
          </div>
        </CardHeader>
        <div className="overflow-x-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={16} className="animate-spin text-muted" />
            </div>
          ) : practices.length ? (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-bg-border">
                  {["Active", "Practice", "Domain", "Cadence", "Enforcement", "Followed", "Skipped"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left text-muted font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {practices.map((p) => (
                  <tr key={p.id} className="border-b border-bg-border/50 hover:bg-bg-hover transition-colors">
                    <td className="px-4 py-2.5">
                      <button
                        onClick={() => togglePractice.mutate(p.id, {
                          onSuccess: () => toast.success(`Practice ${p.active ? "disabled" : "enabled"}`),
                          onError: () => toast.error("Failed to update practice"),
                        })}
                        className="text-muted hover:text-white transition-colors"
                        title={p.active ? "Disable practice" : "Enable practice"}
                      >
                        {p.active
                          ? <ToggleRight size={18} className="text-success" />
                          : <ToggleLeft size={18} className="text-muted" />
                        }
                      </button>
                    </td>
                    <td className="px-4 py-2.5 text-white/80 max-w-sm">{p.text}</td>
                    <td className="px-4 py-2.5 font-mono text-muted">{p.domain}</td>
                    <td className="px-4 py-2.5 font-mono text-muted">{p.cadence}</td>
                    <td className="px-4 py-2.5">
                      <EnforcementControl
                        practice={p}
                        onChange={(level) => setEnforcement.mutate({ id: p.id, level }, {
                          onSuccess: () => toast.success(`Enforcement set to "${level}"`, { description: p.text }),
                          onError: () => toast.error("Failed to update enforcement"),
                        })}
                      />
                    </td>
                    <td className="px-4 py-2.5 text-white/80">{p.times_followed}</td>
                    <td className="px-4 py-2.5 text-white/80">{p.times_skipped}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState
              icon={<ClipboardList size={20} />}
              title="No practices declared yet"
              description="Add your first development practice — e.g. write tests before implementation."
              action={
                <button onClick={() => setShowForm(true)} className="btn btn-primary">
                  <Plus size={12} />
                  New Practice
                </button>
              }
            />
          )}
        </div>
      </Card>
    </div>
  );
}
