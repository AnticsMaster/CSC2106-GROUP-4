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
import type { OccupancyDataPoint } from "../types";

interface OccupancyChartProps {
  history: OccupancyDataPoint[];
  forecast?: OccupancyDataPoint[];
  loading?: boolean;
}

export function OccupancyChart({
  history,
  forecast = [],
  loading = false,
}: OccupancyChartProps) {
  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-slate-400">
        Loading history...
      </div>
    );
  }

  if (history.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-slate-400">
        No historical data available yet.
        <br />
        Data will appear once the bridge script starts publishing.
      </div>
    );
  }

  // Combine history + forecast, marking forecast points
  const chartData = [
    ...history.map((p) => ({ ...p, type: "actual" as const })),
    ...forecast.map((p) => ({ ...p, type: "forecast" as const })),
  ];

  // Find where forecast starts for the reference line
  const forecastStartTime =
    forecast.length > 0 ? history[history.length - 1]?.time : null;

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={chartData}
          margin={{ top: 8, right: 8, left: -16, bottom: 0 }}
        >
          <defs>
            <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="colorForecast" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.2} />
              <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis
            dataKey="timeLabel"
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={{
              fontSize: 12,
              borderRadius: 8,
              border: "1px solid #e2e8f0",
              boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
            }}
            formatter={(value, _name, props) => {
              const label =
                (props as { payload?: { type?: string } }).payload?.type === "forecast"
                  ? "Predicted Students"
                  : "Students";
              return [String(value ?? 0), label];
            }}
          />
          {forecastStartTime && (
            <ReferenceLine
              x={
                chartData.find((d) => d.time === forecastStartTime)
                  ?.timeLabel ?? ""
              }
              stroke="#f59e0b"
              strokeDasharray="4 4"
              label={{
                value: "Now",
                position: "top",
                fill: "#f59e0b",
                fontSize: 11,
              }}
            />
          )}
          <Area
            type="monotone"
            dataKey="count"
            stroke="#3b82f6"
            fill="url(#colorCount)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
