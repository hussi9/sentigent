import { useState } from "react";
import { toast } from "sonner";
import { Route, Loader2, PlayCircle, RefreshCw } from "lucide-react";
import { useRoutingSeeds, useReconcileRouting } from "@/api/hooks";
import { Card, CardHeader, CardTitle, CardBody, StatCard, Badge, OutcomeBadge, EmptyState } from "@/components/ui";
import type { RoutingReconcileResult } from "@/types";

function ReconcileResultCard({ result }: { result: RoutingReconcileResult }) {
  const isDryRun = !!result.dry_run;
  return (
    <div className="p-4 rounded-lg bg-bg-elevated border border-bg-border">
      <div className="flex items-center gap-2 mb-3">
        <Badge variant={isDryRun ? "info" : "success"}>{isDryRun ? "Dry run" : "Reconciled"}</Badge>
        <span className="text-[10px] text-muted">
          {result.parsed_routes} routes parsed · {result.invocations} invocations parsed
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
        {isDryRun ? (
          <>
            <div><div className="text-muted text-[10px] uppercase tracking-wider">Seen</div><div className="text-white font-semibold">{result.seen ?? 0}</div></div>
            <div><div className="text-muted text-[10px] uppercase tracking-wider">Would reinforce</div><div className="text-success font-semibold">{result.would_reinforce ?? 0}</div></div>
            <div><div className="text-muted text-[10px] uppercase tracking-wider">Would demote</div><div className="text-danger font-semibold">{result.would_demote ?? 0}</div></div>
            <div><div className="text-muted text-[10px] uppercase tracking-wider">Thin</div><div className="text-white font-semibold">{result.thin ?? 0}</div></div>
          </>
        ) : (
          <>
            <div><div className="text-muted text-[10px] uppercase tracking-wider">Seen</div><div className="text-white font-semibold">{result.seen ?? 0}</div></div>
            <div><div className="text-muted text-[10px] uppercase tracking-wider">Reinforced</div><div className="text-success font-semibold">{result.reinforced ?? 0}</div></div>
            <div><div className="text-muted text-[10px] uppercase tracking-wider">Demoted</div><div className="text-danger font-semibold">{result.demoted ?? 0}</div></div>
            <div><div className="text-muted text-[10px] uppercase tracking-wider">Unchanged</div><div className="text-white font-semibold">{result.unchanged ?? 0}</div></div>
            <div><div className="text-muted text-[10px] uppercase tracking-wider">Unknown</div><div className="text-white font-semibold">{result.unknown ?? 0}</div></div>
          </>
        )}
      </div>
    </div>
  );
}

export function Routing() {
  const { data, isLoading } = useRoutingSeeds();
  const reconcile = useReconcileRouting();
  const [lastResult, setLastResult] = useState<RoutingReconcileResult | null>(null);

  const seeds = data?.seeds ?? [];
  const counts = data?.counts ?? { correct: 0, incorrect: 0, neutral: 0 };

  function runReconcile(dryRun: boolean) {
    reconcile.mutate(dryRun, {
      onSuccess: (result) => {
        setLastResult(result);
        toast.success(dryRun ? "Dry run complete" : "Reconciliation complete");
      },
      onError: () => toast.error("Reconcile failed"),
    });
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Seeds" value={seeds.length} color="accent" icon={<Route size={14} />} />
        <StatCard label="Correct" value={counts.correct} color="success" />
        <StatCard label="Incorrect" value={counts.incorrect} color={counts.incorrect > 0 ? "danger" : "default"} />
        <StatCard label="Neutral" value={counts.neutral} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle icon={<Route size={14} />}>Reconciliation</CardTitle>
          <div className="flex items-center gap-2">
            <button
              onClick={() => runReconcile(true)}
              disabled={reconcile.isPending}
              className="btn btn-ghost flex items-center gap-1.5 px-3 py-1.5 text-xs border border-bg-border rounded-md disabled:opacity-40"
            >
              {reconcile.isPending ? <Loader2 size={12} className="animate-spin" /> : <PlayCircle size={12} />}
              Dry run
            </button>
            <button
              onClick={() => runReconcile(false)}
              disabled={reconcile.isPending}
              className="btn btn-primary flex items-center gap-1.5 px-3 py-1.5 text-xs disabled:opacity-40"
            >
              {reconcile.isPending ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              Reconcile now
            </button>
          </div>
        </CardHeader>
        <CardBody>
          {lastResult ? (
            <ReconcileResultCard result={lastResult} />
          ) : (
            <p className="text-xs text-muted">
              Run a dry run to preview what reconciliation would change, or reconcile now to fold
              skill-router follow/ignore signal into routing_seeds outcomes.
            </p>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle icon={<Route size={14} />}>Routing Seeds</CardTitle>
          <Badge variant="muted">{seeds.length} total</Badge>
        </CardHeader>
        <div className="overflow-x-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={16} className="animate-spin text-muted" />
            </div>
          ) : seeds.length ? (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-bg-border">
                  {["Skill", "Agent", "Model", "Confidence", "Outcome", "Prompt Hash"].map((h) => (
                    <th key={h} className="px-4 py-2.5 text-left text-muted font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {seeds.map((s) => (
                  <tr key={s.prompt_hash} className="border-b border-bg-border/50 hover:bg-bg-hover transition-colors">
                    <td className="px-4 py-2.5 font-mono text-white/80">{s.skill}</td>
                    <td className="px-4 py-2.5 font-mono text-accent-light">{s.agent}</td>
                    <td className="px-4 py-2.5 font-mono text-muted">{s.model}</td>
                    <td className="px-4 py-2.5 text-white/80">{s.confidence.toFixed(2)}</td>
                    <td className="px-4 py-2.5"><OutcomeBadge outcome={s.outcome} /></td>
                    <td className="px-4 py-2.5 font-mono text-muted/70 max-w-[140px] truncate" title={s.prompt_hash}>
                      {s.prompt_hash}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState
              icon={<Route size={20} />}
              title="No routing seeds yet"
              description="Seeds appear once the skill-router records follow/ignore signal for routed prompts."
            />
          )}
        </div>
      </Card>
    </div>
  );
}
