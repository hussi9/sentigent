import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { TimelinePoint } from "@/types";

interface Props {
  data: TimelinePoint[];
  height?: number;
  color?: string;
  showReference?: boolean;
}

function formatDay(d: string) {
  const dt = new Date(d);
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

interface TooltipProps {
  active?: boolean;
  payload?: Array<{ value: number; payload: TimelinePoint }>;
  label?: string;
}

function CustomTooltip({ active, payload, label }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const pct = (d.score * 100).toFixed(1);
  const isGood = d.score >= 0.75;

  return (
    <div className="rounded-xl px-3.5 py-2.5 text-xs shadow-glow-sm"
      style={{
        background: "#141b26",
        border: "1px solid rgba(30,41,59,0.9)",
        backdropFilter: "blur(8px)",
      }}>
      <div className="text-muted text-[10px] mb-1.5 font-medium">{label}</div>
      <div className={`text-base font-bold tabular leading-none mb-1 ${isGood ? "text-gradient-green" : "text-gradient-amber"}`}>
        {pct}%
      </div>
      <div className="text-muted text-[10px]">{d.correct}/{d.total} correct</div>
    </div>
  );
}

export function ScoreTimeline({ data, height = 180, color = "#7c3aed", showReference = true }: Props) {
  if (!data.length) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 text-xs text-muted" style={{ height }}>
        <div className="w-8 h-8 rounded-lg bg-bg-elevated flex items-center justify-center opacity-40">
          <span>📈</span>
        </div>
        No timeline data yet
      </div>
    );
  }

  const gradId = `grad-${color.replace("#", "")}`;
  const chartData = data.map((d) => ({
    ...d,
    day: formatDay(d.day),
    scorePct: Math.round(d.score * 1000) / 10,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={chartData} margin={{ top: 6, right: 4, bottom: 0, left: -18 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.25} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>

        <CartesianGrid vertical={false} stroke="rgba(255,255,255,0.03)" />

        {showReference && (
          <ReferenceLine y={75} stroke="rgba(16, 185, 129, 0.2)" strokeDasharray="3 3" />
        )}

        <XAxis
          dataKey="day"
          tick={{ fontSize: 10, fill: "#475569", fontFamily: "Inter" }}
          axisLine={false}
          tickLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fontSize: 10, fill: "#475569", fontFamily: "Inter" }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v: number) => `${v}%`}
        />

        <Tooltip content={<CustomTooltip />} cursor={{ stroke: "rgba(124,58,237,0.2)", strokeWidth: 1 }} />

        <Area
          type="monotone"
          dataKey="scorePct"
          stroke={color}
          strokeWidth={2}
          fill={`url(#${gradId})`}
          dot={false}
          activeDot={{ r: 4, fill: color, stroke: "rgba(124,58,237,0.3)", strokeWidth: 3 }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
