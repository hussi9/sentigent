const SIGNAL_CONFIG: Record<string, { color: string; glow: string }> = {
  caution:     { color: "#f59e0b", glow: "rgba(245, 158, 11, 0.3)" },
  doubt:       { color: "#3b82f6", glow: "rgba(59, 130, 246, 0.3)" },
  urgency:     { color: "#ef4444", glow: "rgba(239, 68, 68, 0.3)" },
  confidence:  { color: "#10b981", glow: "rgba(16, 185, 129, 0.3)" },
  frustration: { color: "#a78bfa", glow: "rgba(167, 139, 250, 0.3)" },
};

interface Props {
  signals: Record<string, number>;
  compact?: boolean;
}

export function SignalBars({ signals, compact }: Props) {
  const entries = Object.entries(signals)
    .filter(([, v]) => v > 0.01)
    .sort(([, a], [, b]) => b - a);

  if (!entries.length) return <span className="text-muted/40 text-xs">—</span>;

  if (compact) {
    return (
      <div className="flex gap-0.5 items-end h-4">
        {entries.slice(0, 4).map(([name, val]) => {
          const cfg = SIGNAL_CONFIG[name] ?? { color: "#64748b", glow: "transparent" };
          const heightPct = Math.max(25, val * 100);
          return (
            <div
              key={name}
              title={`${name}: ${(val * 100).toFixed(0)}%`}
              className="w-1.5 rounded-sm flex-shrink-0 transition-all"
              style={{
                height: `${heightPct}%`,
                backgroundColor: cfg.color,
                boxShadow: `0 0 4px ${cfg.glow}`,
                opacity: 0.85,
              }}
            />
          );
        })}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {entries.map(([name, val]) => {
        const cfg = SIGNAL_CONFIG[name] ?? { color: "#64748b", glow: "transparent" };
        return (
          <div key={name} className="flex items-center gap-2.5">
            <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: cfg.color }} />
            <span className="text-[11px] text-muted w-20 capitalize font-medium">{name}</span>
            <div className="flex-1 h-1.5 rounded-full overflow-hidden"
              style={{ background: "rgba(255,255,255,0.05)" }}>
              <div
                className="h-full rounded-full"
                style={{
                  width: `${val * 100}%`,
                  background: `linear-gradient(90deg, ${cfg.color}, ${cfg.color}aa)`,
                  boxShadow: `0 0 6px ${cfg.glow}`,
                  transition: "width 0.5s ease",
                }}
              />
            </div>
            <span className="text-[10px] text-muted w-8 text-right tabular font-mono">
              {(val * 100).toFixed(0)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}
