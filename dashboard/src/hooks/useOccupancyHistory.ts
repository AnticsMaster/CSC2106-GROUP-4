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
import type { OccupancyDataPoint } from "../types";

/**
 * Real-time hook that fetches occupancy history for a given room.
 * Returns the most recent `maxPoints` data points, ordered by timestamp.
 */
export function useOccupancyHistory(
  roomId: string | null,
  maxPoints = 6000,
) {
  const [data, setData] = useState<OccupancyDataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!roomId) {
      setData([]);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    const now = new Date();
    const twentyFourHoursAgo = new Timestamp(
      Math.floor((now.getTime() - 24 * 60 * 60 * 1000) / 1000),
      0
    );

    const q = query(
      collection(db, "occupancy_history"),
      where("roomId", "==", roomId),
      where("timestamp", ">=", twentyFourHoursAgo),
      orderBy("timestamp", "desc"),
      limit(maxPoints),
    );

    const unsubscribe = onSnapshot(
      q,
      (snapshot) => {
        const points: OccupancyDataPoint[] = snapshot.docs
          .map((doc) => {
            const d = doc.data();
            const ts: Timestamp | null = d.timestamp ?? null;
            if (!ts) return null;
            const date = ts.toDate();
            return {
              time: date.getTime(),
              timeLabel: date.toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              }),
              count: d.count ?? 0,
              occupied: d.occupied ?? false,
            } satisfies OccupancyDataPoint;
          })
          .filter((p): p is OccupancyDataPoint => p !== null)
          // Reverse so oldest is first (for left-to-right chart)
          .reverse();

        setData(points);
        setLoading(false);
      },
      (err) => {
        console.error("occupancy_history snapshot error:", err);
        setError(err.message);
        setLoading(false);
      },
    );

    return () => unsubscribe();
  }, [roomId, maxPoints]);

  return { data, loading, error };
}
