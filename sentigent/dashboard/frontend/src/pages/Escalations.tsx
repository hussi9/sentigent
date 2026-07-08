import { toast } from "sonner";
import { AlertOctagon, CheckCircle2, SkipForward, UserCog, Loader2 } from "lucide-react";
import { useEscalations, useAnswerEscalation } from "@/api/hooks";
import { Card, CardHeader, CardTitle, StatCard, Badge, EmptyState } from "@/components/ui";
import type { Escalation, EscalationDecision } from "@/types";

function formatAge(askedAt: number): string {
  const seconds = Math.max(0, Date.now() / 1000 - askedAt);
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function EscalationRow({ escalation, onAnswer, pending }: {
  escalation: Escalation;
  onAnswer: (loopId: string, decision: EscalationDecision) => void;
  pending: boolean;
}) {
  return (
    <div className="p-4 rounded-lg bg-bg-elevated border border-bg-border flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-semibold text-white truncate">{escalation.title}</span>
            <Badge variant="muted">step {escalation.step}</Badge>
          </div>
          <p className="text-xs text-muted">{escalation.blocker}</p>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[10px] text-muted/70 font-mono">{formatAge(escalation.asked_at)}</div>
          <div className="text-[10px] text-muted/50 font-mono truncate max-w-[140px]" title={escalation.loop_id}>
            {escalation.loop_id}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          disabled={pending}
          onClick={() => onAnswer(escalation.loop_id, "approve")}
          className="btn flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-success-dim hover:bg-success/25 text-success-light border border-success/25 rounded-md transition-colors disabled:opacity-40"
        >
          <CheckCircle2 size={12} />
          Approve
        </button>
        <button
          disabled={pending}
          onClick={() => onAnswer(escalation.loop_id, "skip")}
          className="btn flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-warning-dim hover:bg-warning/25 text-warning-light border border-warning/25 rounded-md transition-colors disabled:opacity-40"
        >
          <SkipForward size={12} />
          Skip
        </button>
        <button
          disabled={pending}
          onClick={() => onAnswer(escalation.loop_id, "takeover")}
          className="btn flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-accent/15 hover:bg-accent/25 text-accent-light border border-accent/25 rounded-md transition-colors disabled:opacity-40"
        >
          <UserCog size={12} />
          Takeover
        </button>
      </div>
    </div>
  );
}

export function Escalations() {
  const { data, isLoading } = useEscalations();
  const answerEscalation = useAnswerEscalation();

  const pending = data?.pending ?? [];

  function handleAnswer(loopId: string, decision: EscalationDecision) {
    answerEscalation.mutate({ loopId, decision }, {
      onSuccess: () => toast.success(`Escalation ${decision === "approve" ? "approved" : decision === "skip" ? "skipped" : "taken over"}`),
      onError: () => toast.error("Failed to answer escalation"),
    });
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Pending Escalations"
          value={pending.length}
          color={pending.length > 0 ? "warning" : "default"}
          icon={<AlertOctagon size={14} />}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle icon={<AlertOctagon size={14} />}>Pending Human Decisions</CardTitle>
          <Badge variant={pending.length > 0 ? "warning" : "muted"}>{pending.length} waiting</Badge>
        </CardHeader>
        <div className="p-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={16} className="animate-spin text-muted" />
            </div>
          ) : pending.length ? (
            <div className="space-y-3">
              {pending.map((e) => (
                <EscalationRow
                  key={e.loop_id}
                  escalation={e}
                  onAnswer={handleAnswer}
                  pending={answerEscalation.isPending}
                />
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<CheckCircle2 size={20} />}
              title="No escalations pending"
              description="All autonomous loops are running without a blocker that needs a human decision."
            />
          )}
        </div>
      </Card>
    </div>
  );
}
