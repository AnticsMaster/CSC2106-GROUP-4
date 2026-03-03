import type { OccupancyPrediction } from "../types";

interface PredictionBadgeProps {
  prediction: OccupancyPrediction | null;
}

const trendIcons: Record<OccupancyPrediction["trend"], string> = {
  rising: "\u2191",   // ↑
  falling: "\u2193",  // ↓
  stable: "\u2192",   // →
};

const trendColors: Record<OccupancyPrediction["trend"], string> = {
  rising: "bg-amber-100 text-amber-800 border-amber-200",
  falling: "bg-blue-100 text-blue-800 border-blue-200",
  stable: "bg-slate-100 text-slate-700 border-slate-200",
};

export function PredictionBadge({ prediction }: PredictionBadgeProps) {
  if (!prediction) return null;

  const icon = trendIcons[prediction.trend];
  const color = trendColors[prediction.trend];

  return (
    <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${color}`}>
      <div className="flex items-center gap-1.5 font-semibold">
        <span className="text-sm">{icon}</span>
        <span>
          Trend: {prediction.trend} &middot; ~{prediction.predictedCount}{" "}
          students
        </span>
      </div>
      <p className="mt-0.5 opacity-80">{prediction.summary}</p>
    </div>
  );
}
