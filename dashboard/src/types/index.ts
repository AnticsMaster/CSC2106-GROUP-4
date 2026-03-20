import { Timestamp } from "firebase/firestore";

/** One heatmap snapshot — 4 zone scores from the classroom PIRs. */
export interface HeatmapData {
  /** Scores 0–3 for zones [Z1, Z2, Z3, Z4].
   *  0 = none, 1 = low, 2 = medium, 3 = high */
  zones: number[];
  /** Human-readable labels matching zones: "none" | "low" | "medium" | "high" */
  zoneLabels: string[];
  lastUpdated: Timestamp | null;
  picoTimestamp?: number;
}

export interface Classroom {
  roomId: string;
  roomName: string;
  occupied: boolean;
  count: number;
  lastUpdated: Timestamp | null;
  deviceStatus: "online" | "offline" | "unknown";
  picoTimestamp?: number;
  maxOccupancy?: number;
  /** Latest heatmap snapshot — undefined until first "H" frame arrives. */
  heatmap?: HeatmapData;
}

/** A single data point from the occupancy_history Firestore collection. */
export interface OccupancyHistoryEntry {
  roomId: string;
  roomName: string;
  occupied: boolean;
  count: number;
  timestamp: Timestamp | null;
  picoTimestamp?: number;
}

/** Chart-friendly representation of a history entry (epoch ms for x-axis). */
export interface OccupancyDataPoint {
  time: number; // epoch ms
  timeLabel: string; // formatted HH:MM
  count: number;
  occupied: boolean;
}

/** Prediction result for a classroom. */
export interface OccupancyPrediction {
  trend: "rising" | "falling" | "stable";
  predictedCount: number;
  confidence: "low" | "medium" | "high";
  summary: string; // e.g. "Likely busy in 30 min"
}
