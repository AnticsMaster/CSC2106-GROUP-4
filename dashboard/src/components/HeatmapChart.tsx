import { useState, useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useHeatmapHistory } from "../hooks/useHeatmapHistory";
import type { HeatmapDataPoint } from "../types";

// ── Score → colour mapping (matches HeatmapGrid for consistency) ───────────────
const SCORE_COLORS = [
  "#e2e8f0",  // 0 – none    (slate-200)
  "#22c55e",  // 1 – low     (green-500)
  "#f59e0b",  // 2 – medium  (amber-500)
  "#ef4444",  // 3 – high    (red-500)
];

const SCORE_LABELS: Record<number, string> = {
  0: "No activity",
  1: "Low",
  2: "Medium",
  3: "High",
};

// Badge background tints (10% opacity version of each colour)
const SCORE_BG = [
  "bg-slate-100 text-slate-400",
  "bg-green-100 text-green-700",
  "bg-amber-100 text-amber-700",
  "bg-red-100   text-red-700",
];

// ── Zone definitions ───────────────────────────────────────────────────────────
const ZONES = [
  { key: "z1" as const, label: "Zone 1", pin: "GP0"  },
  { key: "z2" as const, label: "Zone 2", pin: "GP6"  },
  { key: "z3" as const, label: "Zone 3", pin: "GP8"  },
  { key: "z4" as const, label: "Zone 4", pin: "GP26" },
];

// ── Time-range options ─────────────────────────────────────────────────────────
const RANGES = [
  { label: "30 min", points: 30  },
  { label: "1 hr",   points: 60  },
  { label: "4 hr",   points: 240 },
] as const;

type RangeLabel = (typeof RANGES)[number]["label"];

// ── Tooltip for a single-zone bar chart ───────────────────────────────────────
function ZoneTooltip({
  active,
  payload,
  label,
  zoneLabel,
}: {
  active?: boolean;
  payload?: { value: number }[];
  label?: string;
  zoneLabel: string;
}) {
  if (!active || !payload?.length) return null;
  const score = payload[0].value ?? 0;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs shadow-md">
      <p className="font-semibold text-slate-500">{label}</p>
      <p className="mt-0.5 font-bold" style={{ color: SCORE_COLORS[score] }}>
        {zoneLabel}: {SCORE_LABELS[score]}
      </p>
    </div>
  );
}

// ── Individual zone bar chart ─────────────────────────────────────────────────
interface ZoneBarChartProps {
  data: HeatmapDataPoint[];
  zoneKey: "z1" | "z2" | "z3" | "z4";
  label: string;
  pin: string;
}

function ZoneBarChart({ data, zoneKey, label, pin }: ZoneBarChartProps) {
  const currentScore = data.length > 0 ? (data[data.length - 1][zoneKey] ?? 0) : 0;

  return (
    <div className="rounded-xl border border-slate-100 bg-white p-3">
      {/* Zone header */}
      <div className="mb-2 flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold text-slate-700">{label}</p>
          <p className="text-[10px] text-slate-400">{pin}</p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${SCORE_BG[currentScore]}`}>
          {SCORE_LABELS[currentScore]}
        </span>
      </div>

      {/* Bar chart — no Y-axis, height conveys intensity (like Google Maps) */}
      <div className="h-32">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            margin={{ top: 2, right: 0, left: 0, bottom: 0 }}
            barCategoryGap="15%"
          >
            <XAxis
              dataKey="timeLabel"
              tick={{ fontSize: 9, fill: "#94a3b8" }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            {/* Y hidden — bar height is the visual cue, labels would add clutter */}
            <YAxis domain={[0, 3]} hide />
            <Tooltip
              cursor={{ fill: "rgba(0,0,0,0.04)" }}
              content={
                <ZoneTooltip zoneLabel={label} />
              }
            />
            <Bar dataKey={zoneKey} radius={[3, 3, 0, 0]} maxBarSize={14}>
              {data.map((entry, i) => (
                <Cell key={i} fill={SCORE_COLORS[entry[zoneKey] ?? 0]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────
interface HeatmapChartProps {
  roomId: string;
}

export function HeatmapChart({ roomId }: HeatmapChartProps) {
  const [range, setRange] = useState<RangeLabel>("30 min");
  const selectedPoints = RANGES.find((r) => r.label === range)?.points ?? 60;

  // Load 240 points once — slicing for range is instant, no re-fetch needed
  const { data, loading, error } = useHeatmapHistory(roomId, 240);

  const chartData = useMemo(
    () => data.slice(-selectedPoints),
    [data, selectedPoints],
  );

  // ── States ──────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-slate-400">
        Loading zone history…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
        <p className="font-semibold">Failed to load heatmap history</p>
        <p className="mt-1 break-all">{error}</p>
        {error.includes("index") && (
          <p className="mt-1">
            A Firestore composite index is required — check the browser console for the direct creation link.
          </p>
        )}
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-center text-sm text-slate-400">
        No zone history yet — data appears after the first 1-minute interval.
      </div>
    );
  }

  return (
    <div>
      {/* Section header + range selector */}
      <div className="mb-3 flex items-center justify-end">
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

      {/* 2×2 grid — one chart per zone */}
      <div className="grid grid-cols-2 gap-2">
        {ZONES.map((z) => (
          <ZoneBarChart
            key={z.key}
            data={chartData}
            zoneKey={z.key}
            label={z.label}
            pin={z.pin}
          />
        ))}
      </div>

      {/* Colour legend */}
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[10px] text-slate-400">
        {SCORE_COLORS.map((c, i) => (
          <span key={i} className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ backgroundColor: c }}
            />
            {SCORE_LABELS[i]}
          </span>
        ))}
        <span className="ml-auto">
          {chartData.length} snapshots · updates every minute
        </span>
      </div>
    </div>
  );
}
