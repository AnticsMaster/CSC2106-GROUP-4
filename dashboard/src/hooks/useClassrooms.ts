import { useEffect, useState } from "react";
import { collection, onSnapshot, query } from "firebase/firestore";
import { db } from "../lib/firebase";
import type { Classroom, HeatmapData } from "../types";

/**
 * Real-time listener for the `classrooms` Firestore collection.
 * Returns the list of classrooms plus loading / error state.
 */
export function useClassrooms() {
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const q = query(collection(db, "classrooms"));

    const unsubscribe = onSnapshot(
      q,
      (snapshot) => {
        const rooms: Classroom[] = snapshot.docs.map((doc) => {
          const d = doc.data();
          // Pull heatmap sub-document if it exists
          const rawHeatmap = d.heatmap;
          const heatmap: HeatmapData | undefined = rawHeatmap
            ? {
                zones: rawHeatmap.zones ?? [0, 0, 0, 0],
                zoneLabels: rawHeatmap.zoneLabels ?? ["none", "none", "none", "none"],
                lastUpdated: rawHeatmap.lastUpdated ?? null,
                picoTimestamp: rawHeatmap.picoTimestamp,
              }
            : undefined;

          return {
            roomId: d.roomId ?? doc.id,
            roomName: d.roomName ?? doc.id,
            occupied: d.occupied ?? false,
            count: d.count ?? 0,
            lastUpdated: d.lastUpdated ?? null,
            lastSeen: d.lastSeen ?? null,
            deviceStatus: d.deviceStatus ?? "unknown",
            picoTimestamp: d.picoTimestamp,
            maxOccupancy: d.maxOccupancy ?? 30,
            heatmap,
          };
        });
        // Sort by room name for consistent ordering
        rooms.sort((a, b) => a.roomName.localeCompare(b.roomName));
        setClassrooms(rooms);
        setLoading(false);
      },
      (err) => {
        console.error("Firestore snapshot error:", err);
        setError(err.message);
        setLoading(false);
      },
    );

    return () => unsubscribe();
  }, []);

  return { classrooms, loading, error };
}
