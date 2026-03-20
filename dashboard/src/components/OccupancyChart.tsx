import { useMemo } from "react";
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
  const chartData = useMemo(() => {
    // We want the actual count and forecast count to be in separate keys
    // so they can be styled differently as separate Area components.
    const actualPoints = history.map((p) => ({
      ...p,
      actualCount: p.count as number | null,
      forecastCount: null as number | null,
      type: "actual" as const,
    }));

    const forecastPoints = forecast.map((p) => ({
      ...p,
      actualCount: null as number | null,
      forecastCount: p.count as number | null,
      type: "forecast" as const,
    }));

    // To connect the actual line to the forecast line, the last actual point
    // must also have a forecastCount equal to its actualCount.
    if (actualPoints.length > 0 && forecastPoints.length > 0) {
      const lastActual = actualPoints[actualPoints.length - 1];
      lastActual.forecastCount = lastActual.actualCount;
    }

    const combined = [...actualPoints, ...forecastPoints];
    return combined.sort((a, b) => a.time - b.time);
  }, [history, forecast]);

  // Find where forecast starts for the reference line
  const forecastStartTime =
    forecast.length > 0 ? history[history.length - 1]?.time : null;

  // X-Axis formatter to show date only when needed
  const formatXAxis = (time: number) => {
    const date = new Date(time);
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();

    if (isToday) {
      return date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
    }
    return date.toLocaleDateString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={chartData}
          margin={{ top: 20, right: 20, left: -16, bottom: 0 }}
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
            dataKey="time"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={formatXAxis}
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            tickLine={false}
            minTickGap={30}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip
            labelFormatter={(label: any) => formatXAxis(Number(label))}
            contentStyle={{
              fontSize: 12,
              borderRadius: 8,
              border: "1px solid #e2e8f0",
              boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
            }}
            itemSorter={(item) => (item.name === "Students" ? -1 : 1)}
          />
          {forecastStartTime && (
            <ReferenceLine
              x={forecastStartTime}
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
            type="linear"
            dataKey="actualCount"
            stroke="#3b82f6"
            fill="url(#colorCount)"
            strokeWidth={3}
            dot={false}
            activeDot={{ r: 4 }}
            name="Students"
          />
          <Area
            type="linear"
            dataKey="forecastCount"
            stroke="#f59e0b"
            fill="url(#colorForecast)"
            strokeWidth={3}
            strokeDasharray="5 5"
            dot={false}
            activeDot={{ r: 4 }}
            name="Predicted Students"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
