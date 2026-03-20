import { useEffect, useState } from "react";
import {
  collection,
  query,
  where,
  orderBy,
  limit,
  onSnapshot,
  Timestamp,
} from "firebase/firestore";
import { db } from "../lib/firebase";
import type { HeatmapDataPoint } from "../types";

/**
 * Real-time hook that fetches heatmap history for a given room.
 * Returns the most recent `maxPoints` snapshots ordered oldest → newest.
 * Each snapshot has per-zone scores (0–3) ready for charting.
 */
export function useHeatmapHistory(
  roomId: string | null,
  maxPoints = 240,          // 240 mins = 4 hours at 1 frame/min
) {
  const [data, setData]       = useState<HeatmapDataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  useEffect(() => {
    if (!roomId) {
      setData([]);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    const q = query(
      collection(db, "heatmap_history"),
      where("roomId", "==", roomId),
      orderBy("timestamp", "desc"),
      limit(maxPoints),
    );

    const unsubscribe = onSnapshot(
      q,
      (snapshot) => {
        const points: HeatmapDataPoint[] = snapshot.docs
          .map((doc) => {
            const d = doc.data();
            const ts: Timestamp | null = d.timestamp ?? null;
            if (!ts) return null;
            const date = ts.toDate();
            const zones: number[] = d.zones ?? [0, 0, 0, 0];
            return {
              time:      date.getTime(),
              timeLabel: date.toLocaleTimeString([], {
                hour:   "2-digit",
                minute: "2-digit",
              }),
              z1: zones[0] ?? 0,
              z2: zones[1] ?? 0,
              z3: zones[2] ?? 0,
              z4: zones[3] ?? 0,
            } satisfies HeatmapDataPoint;
          })
          .filter((p): p is HeatmapDataPoint => p !== null)
          // Reverse so oldest is leftmost on the chart
          .reverse();

        setData(points);
        setLoading(false);
      },
      (err) => {
        console.error("heatmap_history snapshot error:", err);
        setError(err.message);
        setLoading(false);
      },
    );

    return () => unsubscribe();
  }, [roomId, maxPoints]);

  return { data, loading, error };
}
