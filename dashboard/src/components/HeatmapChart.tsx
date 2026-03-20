import { useState, useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { useHeatmapHistory } from "../hooks/useHeatmapHistory";

// ── Zone config ────────────────────────────────────────────────────────────────
const ZONES = [
  { key: "z1", label: "Zone 1 (GP0)",  color: "#3b82f6" },  // blue
  { key: "z2", label: "Zone 2 (GP6)",  color: "#22c55e" },  // green
  { key: "z3", label: "Zone 3 (GP8)",  color: "#f59e0b" },  // amber
  { key: "z4", label: "Zone 4 (GP26)", color: "#a855f7" },  // purple
] as const;

const SCORE_LABELS: Record<number, string> = {
  0: "None",
  1: "Low",
  2: "Medium",
  3: "High",
};

// ── Time-range options (number of 1-min data points to show) ──────────────────
const RANGES = [
  { label: "30 min", points: 30  },
  { label: "1 hr",   points: 60  },
  { label: "4 hr",   points: 240 },
] as const;

type RangeLabel = (typeof RANGES)[number]["label"];

// ── Custom tooltip ─────────────────────────────────────────────────────────────
function CustomTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: { color: string; name: string; value: number }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-2.5 text-xs shadow-md">
      <p className="mb-1.5 font-semibold text-slate-600">{label}</p>
      {payload.map((entry) => (
        <p key={entry.name} style={{ color: entry.color }} className="leading-5">
          {entry.name}: <span className="font-semibold">{SCORE_LABELS[entry.value] ?? entry.value}</span>
        </p>
      ))}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────
interface HeatmapChartProps {
  roomId: string;
}

export function HeatmapChart({ roomId }: HeatmapChartProps) {
  const [range, setRange] = useState<RangeLabel>("1 hr");

  const selectedPoints = RANGES.find((r) => r.label === range)?.points ?? 60;

  // Always load 240 points max so switching range is instant (no re-fetch)
  const { data, loading, error } = useHeatmapHistory(roomId, 240);

  // Slice to the selected range client-side
  const chartData = useMemo(
    () => data.slice(-selectedPoints),
    [data, selectedPoints],
  );

  // ── Empty / loading states ─────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex h-52 items-center justify-center text-sm text-slate-400">
        Loading heatmap history…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
        <p className="font-semibold">Failed to load heatmap history</p>
        <p className="mt-1 break-all">{error}</p>
        {error.includes("index") && (
          <p className="mt-1 text-red-600">
            Requires a Firestore composite index — check the browser console for a direct link.
          </p>
        )}
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="flex h-52 items-center justify-center text-center text-sm text-slate-400">
        No heatmap history yet.
        <br />
        Data appears after the first 1-minute interval fires.
      </div>
    );
  }

  return (
    <div>
      {/* Header row with range selector */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-600">Zone Activity History</h3>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r.label}
              onClick={() => setRange(r.label)}
              className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                range === r.label
                  ? "bg-slate-800 text-white"
                  : "bg-slate-100 text-slate-500 hover:bg-slate-200"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div className="h-52 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            margin={{ top: 4, right: 8, left: -20, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              dataKey="timeLabel"
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={[0, 3]}
              ticks={[0, 1, 2, 3]}
              tickFormatter={(v: number) => SCORE_LABELS[v] ?? v}
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              tickLine={false}
              width={48}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 11, paddingTop: 6 }}
            />
            {ZONES.map((z) => (
              <Line
                key={z.key}
                type="stepAfter"
                dataKey={z.key}
                name={z.label}
                stroke={z.color}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 3 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <p className="mt-1.5 text-xs text-slate-400">
        Showing {chartData.length} of {data.length} snapshots · updates every minute
      </p>
    </div>
  );
}
