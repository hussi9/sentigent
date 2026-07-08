import type { Severity } from "@/types";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "success" | "warning" | "danger" | "info" | "accent" | "muted";
  size?: "sm" | "md";
  dot?: boolean;
}

const VARIANT_CLASSES: Record<string, string> = {
  default: "bg-bg-elevated text-muted border-bg-border",
  success: "bg-success-dim text-success-light border-success/20",
  warning: "bg-warning-dim text-warning-light border-warning/25",
  danger: "bg-danger-dim text-danger-light border-danger/25",
  info: "bg-info-dim text-info-light border-info/20",
  accent: "bg-accent/10 text-accent-light border-accent/20",
  muted: "bg-bg-elevated/50 text-muted/60 border-transparent",
};

const DOT_CLASSES: Record<string, string> = {
  default: "bg-muted",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
  accent: "bg-accent-light",
  muted: "bg-muted/40",
};

export function Badge({ children, variant = "default", size = "sm", dot }: BadgeProps) {
  return (
    <span
      className={`
        inline-flex items-center gap-1 border rounded-full font-semibold
        ${size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-0.5 text-xs"}
        ${VARIANT_CLASSES[variant]}
      `}
    >
      {dot && (
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${DOT_CLASSES[variant]}`} />
      )}
      {children}
    </span>
  );
}

const SEVERITY_VARIANTS: Record<Severity, BadgeProps["variant"]> = {
  critical: "danger",
  high: "warning",
  medium: "info",
  low: "muted",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge variant={SEVERITY_VARIANTS[severity]} dot>{severity}</Badge>;
}

const ACTION_LABELS: Record<string, { label: string; variant: BadgeProps["variant"] }> = {
  proceed: { label: "proceed", variant: "success" },
  slow_down: { label: "slow down", variant: "warning" },
  enrich: { label: "enrich", variant: "info" },
  escalate: { label: "escalate", variant: "danger" },
  block: { label: "block", variant: "danger" },
};

export function ActionBadge({ action }: { action: string }) {
  const cfg = ACTION_LABELS[action] ?? { label: action, variant: "muted" as const };
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
}

export function OutcomeBadge({ outcome }: { outcome: string | null }) {
  if (!outcome) return <Badge variant="muted">—</Badge>;
  if (outcome === "correct") return <Badge variant="success" dot>correct</Badge>;
  if (outcome === "incorrect") return <Badge variant="danger" dot>incorrect</Badge>;
  return <Badge variant="muted">neutral</Badge>;
}
