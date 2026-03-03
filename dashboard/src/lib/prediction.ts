import type { OccupancyDataPoint, OccupancyPrediction } from "../types";

/**
 * Predict near-future occupancy based on recent history data.
 *
 * Algorithm:
 * 1. Compute a weighted moving average of the last N data points
 *    (recent points weighted more heavily).
 * 2. Determine trend by comparing the average of the last third
 *    vs. the first third of the window.
 * 3. Extrapolate a predicted count and classify the trend.
 *
 * This is intentionally simple — a demonstration of pattern-based
 * prediction without requiring ML libraries.
 */
export function predictOccupancy(
  history: OccupancyDataPoint[],
  capacity = 40,
): OccupancyPrediction | null {
  if (history.length < 4) {
    return null; // Not enough data to predict
  }

  const recent = history.slice(-30); // Last 30 data points (~7.5 min at 15s interval)
  const n = recent.length;

  // Split into thirds for trend detection
  const thirdSize = Math.max(1, Math.floor(n / 3));
  const firstThird = recent.slice(0, thirdSize);
  const lastThird = recent.slice(n - thirdSize);

  const avgFirst =
    firstThird.reduce((sum, p) => sum + p.count, 0) / firstThird.length;
  const avgLast =
    lastThird.reduce((sum, p) => sum + p.count, 0) / lastThird.length;

  // Weighted moving average (exponential-ish weights)
  let weightedSum = 0;
  let weightTotal = 0;
  for (let i = 0; i < n; i++) {
    const weight = (i + 1) / n; // Linear weight: older=low, newer=high
    weightedSum += recent[i].count * weight;
    weightTotal += weight;
  }
  const weightedAvg = weightedSum / weightTotal;

  // Trend detection
  const delta = avgLast - avgFirst;
  const deltaPercent = capacity > 0 ? Math.abs(delta) / capacity : 0;

  let trend: OccupancyPrediction["trend"];
  if (deltaPercent < 0.05) {
    trend = "stable";
  } else if (delta > 0) {
    trend = "rising";
  } else {
    trend = "falling";
  }

  // Extrapolate: project the trend forward by the same amount
  const predictedCount = Math.max(
    0,
    Math.min(capacity, Math.round(weightedAvg + delta * 0.5)),
  );

  // Confidence based on data quantity and consistency
  let confidence: OccupancyPrediction["confidence"];
  if (n >= 20) {
    confidence = "high";
  } else if (n >= 8) {
    confidence = "medium";
  } else {
    confidence = "low";
  }

  // Human-readable summary
  const summary = buildSummary(trend, predictedCount, capacity, confidence);

  return { trend, predictedCount, confidence, summary };
}

function buildSummary(
  trend: OccupancyPrediction["trend"],
  predicted: number,
  capacity: number,
  confidence: OccupancyPrediction["confidence"],
): string {
  const utilization = capacity > 0 ? predicted / capacity : 0;
  const confidenceLabel =
    confidence === "high" ? "" : ` (${confidence} confidence)`;

  if (trend === "rising") {
    if (utilization > 0.7)
      return `Likely busy soon — ~${predicted} students expected${confidenceLabel}`;
    return `Occupancy trending up — ~${predicted} students expected${confidenceLabel}`;
  }
  if (trend === "falling") {
    if (utilization < 0.15)
      return `Clearing out — likely available soon${confidenceLabel}`;
    return `Occupancy declining — ~${predicted} students expected${confidenceLabel}`;
  }
  // stable
  if (utilization < 0.15)
    return `Expected to stay quiet${confidenceLabel}`;
  if (utilization > 0.7)
    return `Expected to remain busy — ~${predicted} students${confidenceLabel}`;
  return `Stable occupancy — ~${predicted} students expected${confidenceLabel}`;
}

/**
 * Generate forecast data points for the chart.
 * Extends the last known time by `steps` intervals of `intervalMs`.
 */
export function generateForecast(
  history: OccupancyDataPoint[],
  prediction: OccupancyPrediction,
  steps = 8,
  intervalMs = 15_000,
): OccupancyDataPoint[] {
  if (history.length === 0) return [];

  const lastPoint = history[history.length - 1];
  const currentCount = lastPoint.count;
  const targetCount = prediction.predictedCount;
  const forecast: OccupancyDataPoint[] = [];

  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    // Ease towards predicted count
    const count = Math.round(currentCount + (targetCount - currentCount) * t);
    const time = lastPoint.time + i * intervalMs;
    const date = new Date(time);
    forecast.push({
      time,
      timeLabel: date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
      count: Math.max(0, count),
      occupied: count > 0,
    });
  }

  return forecast;
}
