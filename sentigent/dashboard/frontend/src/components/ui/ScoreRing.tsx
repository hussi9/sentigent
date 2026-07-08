interface ScoreRingProps {
  score: number; // 0–1
  size?: number;
  strokeWidth?: number;
  label?: string;
  showGlow?: boolean;
}

function scoreColor(score: number): { stroke: string; glow: string; text: string } {
  if (score >= 0.75) return { stroke: "#10b981", glow: "#10b98180", text: "#34d399" };
  if (score >= 0.5) return { stroke: "#f59e0b", glow: "#f59e0b80", text: "#fbbf24" };
  return { stroke: "#ef4444", glow: "#ef444480", text: "#f87171" };
}

export function ScoreRing({ score, size = 80, strokeWidth = 7, label, showGlow = true }: ScoreRingProps) {
  const r = (size - strokeWidth) / 2;
  const circ = 2 * Math.PI * r;
  const fill = circ * Math.min(Math.max(score, 0), 1);
  const { stroke, glow, text } = scoreColor(score);
  const pct = Math.round(score * 100);

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: size, height: size }}>
        {/* Ambient glow underneath */}
        {showGlow && (
          <div
            className="absolute inset-0 rounded-full pointer-events-none"
            style={{
              background: `radial-gradient(circle, ${glow.replace("80", "30")} 0%, transparent 70%)`,
              filter: "blur(8px)",
            }}
          />
        )}
        <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
          {/* Track */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="rgba(255,255,255,0.05)"
            strokeWidth={strokeWidth}
          />
          {/* Progress */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={stroke}
            strokeWidth={strokeWidth}
            strokeDasharray={`${fill} ${circ - fill}`}
            strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 5px ${glow})` }}
          />
        </svg>
        {/* Center text */}
        <div
          className="absolute inset-0 flex flex-col items-center justify-center"
          style={{ fontSize: size * 0.22, fontWeight: 700, color: text, lineHeight: 1 }}
        >
          <span className="tabular">{pct}</span>
          <span style={{ fontSize: size * 0.12, color: "rgba(255,255,255,0.4)", fontWeight: 500 }}>%</span>
        </div>
      </div>
      {label && (
        <span className="text-[11px] text-muted text-center font-medium">{label}</span>
      )}
    </div>
  );
}
