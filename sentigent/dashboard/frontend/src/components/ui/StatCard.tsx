interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  trend?: "up" | "down" | "neutral";
  trendValue?: string;
  color?: "default" | "success" | "warning" | "danger" | "accent";
  icon?: React.ReactNode;
}

const COLOR_CONFIG = {
  default: {
    text: "text-white",
    bg: "transparent",
    icon: "text-muted/50 bg-bg-elevated",
  },
  success: {
    text: "text-gradient-green",
    bg: "bg-gradient-green",
    icon: "text-success bg-success-dim",
  },
  warning: {
    text: "text-gradient-amber",
    bg: "bg-gradient-amber",
    icon: "text-warning bg-warning-dim",
  },
  danger: {
    text: "text-danger-light",
    bg: "bg-gradient-red",
    icon: "text-danger bg-danger-dim",
  },
  accent: {
    text: "text-gradient",
    bg: "bg-gradient-purple",
    icon: "text-accent-light bg-accent/10",
  },
};

export function StatCard({ label, value, sub, trend, trendValue, color = "default", icon }: StatCardProps) {
  const cfg = COLOR_CONFIG[color];

  return (
    <div className={`bg-bg-surface border border-bg-border rounded-xl p-5 flex flex-col gap-3 stat-card relative overflow-hidden ${cfg.bg}`}>
      {/* Subtle grid texture */}
      <div className="absolute inset-0 pointer-events-none"
        style={{ backgroundImage: "radial-gradient(rgba(255,255,255,0.015) 1px, transparent 1px)", backgroundSize: "20px 20px" }} />

      <div className="flex items-start justify-between relative">
        <span className="text-[11px] font-semibold text-muted uppercase tracking-widest">{label}</span>
        {icon && (
          <span className={`p-1.5 rounded-lg ${cfg.icon} transition-colors`}>
            {icon}
          </span>
        )}
      </div>

      <div className={`text-[28px] font-bold tracking-tight tabular leading-none relative ${cfg.text}`}>
        {value}
      </div>

      {(sub || trend) && (
        <div className="flex items-center gap-2 text-xs relative">
          {sub && <span className="text-muted">{sub}</span>}
          {trend && trendValue && (
            <span className={`flex items-center gap-0.5 font-medium ${
              trend === "up" ? "text-success" : trend === "down" ? "text-danger" : "text-muted"
            }`}>
              {trend === "up" ? "↑" : trend === "down" ? "↓" : "→"} {trendValue}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
