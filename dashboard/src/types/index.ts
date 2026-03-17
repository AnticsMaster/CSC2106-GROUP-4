import { Timestamp } from "firebase/firestore";

export interface Classroom {
  roomId: string;
  roomName: string;
  occupied: boolean;
  count: number;
  lastUpdated: Timestamp | null;
  deviceStatus: "online" | "offline" | "unknown";
  picoTimestamp?: number;
  maxOccupancy?: number;
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
