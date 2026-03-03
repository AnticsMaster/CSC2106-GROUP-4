import type { Classroom } from "../types";
import { StatusBadge } from "./StatusBadge";

function formatTime(ts: Classroom["lastUpdated"]): string {
  if (!ts) return "N/A";
  try {
    const date = ts.toDate();
    return date.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "N/A";
  }
}

interface ClassroomCardProps {
  room: Classroom;
}

export function ClassroomCard({ room }: ClassroomCardProps) {
  const borderColor =
    room.deviceStatus === "offline"
      ? "border-gray-300"
      : room.occupied
        ? "border-red-300"
        : "border-green-300";

  return (
    <div
      className={`rounded-xl border-2 ${borderColor} bg-white p-5 shadow-sm transition-shadow hover:shadow-md`}
    >
      {/* Header */}
      <div className="mb-3 flex items-start justify-between">
        <h3 className="text-lg font-semibold text-slate-800">
          {room.roomName}
        </h3>
        <StatusBadge
          occupied={room.occupied}
          deviceStatus={room.deviceStatus}
        />
      </div>

      {/* Student count */}
      <div className="mb-4">
        <p className="text-3xl font-bold text-slate-900">{room.count}</p>
        <p className="text-sm text-slate-500">students detected</p>
      </div>

      {/* Footer meta */}
      <div className="flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-400">
        <span>ID: {room.roomId}</span>
        <span>Updated: {formatTime(room.lastUpdated)}</span>
      </div>
    </div>
  );
}
