import { useState, useEffect } from "react";
import type { Classroom } from "../types";

interface DeviceHealthProps {
  classrooms: Classroom[];
}

function formatRelativeTime(ts: Classroom["lastUpdated"]): string {
  if (!ts) return "Never";
  try {
    const date = ts.toDate();
    const diff = Date.now() - date.getTime();
    const seconds = Math.floor(diff / 1000);

    if (seconds < 5) return "Just now";
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    return `${hours}h ago`;
  } catch {
    return "Unknown";
  }
}

export function DeviceHealth({ classrooms }: DeviceHealthProps) {
  const [now, setNow] = useState(() => Date.now());

  // Force re-render every second to update "Last Heartbeat"
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-slate-800">Device Health Management</h2>
        <p className="text-sm text-slate-500">Monitoring real-time connectivity and heartbeat for all Pico W devices.</p>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-6 py-4">Room / Device</th>
              <th className="px-6 py-4">Status</th>
              <th className="px-6 py-4">Last Heartbeat</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {classrooms.map((room) => {
              const isOnline = room.deviceStatus === "online";
              // Heartbeat uses lastSeen (status updates), fallback to lastUpdated (data updates)
              const heartbeatTs = room.lastSeen || room.lastUpdated;
              const heartbeatDate = heartbeatTs?.toDate();
              const isStale = heartbeatDate && (now - heartbeatDate.getTime() > 120000); // 2 mins

              return (
                <tr key={room.roomId} className="hover:bg-slate-50/50 transition-colors">
                  <td className="px-6 py-4">
                    <div className="font-semibold text-slate-800">{room.roomName}</div>
                    <div className="text-xs text-slate-400">ID: {room.roomId}</div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <span className={`relative flex h-2.5 w-2.5`}>
                        {isOnline && !isStale && (
                          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75"></span>
                        )}
                        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${
                          isOnline && !isStale ? "bg-green-500" : "bg-red-500"
                        }`}></span>
                      </span>
                      <span className={`font-medium ${
                        isOnline && !isStale ? "text-green-700" : "text-red-700"
                      }`}>
                        {isOnline && !isStale ? "Online" : "Offline"}
                      </span>
                    </div>
                  </td>
                  <td className={`px-6 py-4 font-mono text-xs ${isStale ? "text-amber-600 font-bold" : "text-slate-600"}`}>
                    {formatRelativeTime(heartbeatTs)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {classrooms.length === 0 && (
          <div className="py-20 text-center text-slate-400">
            No devices currently registered in Firestore.
          </div>
        )}
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-green-100 bg-green-50 p-4">
          <p className="text-xs font-bold uppercase text-green-600">Online</p>
          <p className="text-2xl font-bold text-green-700">
            {classrooms.filter(r => {
              const ts = r.lastSeen || r.lastUpdated;
              return r.deviceStatus === "online" && (!ts || (now - ts.toDate().getTime() < 120000));
            }).length}
          </p>
        </div>
        <div className="rounded-lg border border-red-100 bg-red-50 p-4">
          <p className="text-xs font-bold uppercase text-red-600">Offline</p>
          <p className="text-2xl font-bold text-red-700">
            {classrooms.filter(r => {
              const ts = r.lastSeen || r.lastUpdated;
              const isStale = ts && (now - ts.toDate().getTime() >= 120000);
              return r.deviceStatus !== "online" || isStale;
            }).length}
          </p>
        </div>
      </div>
    </div>
  );
}
