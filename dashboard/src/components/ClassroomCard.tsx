import { useState, useEffect } from "react";
import { doc, updateDoc, deleteDoc } from "firebase/firestore";
import { db } from "../lib/firebase";
import type { Classroom } from "../types";
import { StatusBadge } from "./StatusBadge";
import { HeatmapMini } from "./HeatmapGrid";

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
  isAdmin?: boolean;
  onClick?: () => void;
}

export function ClassroomCard({ room, isAdmin, onClick }: ClassroomCardProps) {
  const [editing, setEditing] = useState(false);
  const [inputVal, setInputVal] = useState("");
  const [saving, setSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5000); // Check every 5s
    return () => clearInterval(timer);
  }, []);

  const maxOcc = room.maxOccupancy ?? Infinity;
  const heartbeatTs = room.lastSeen || room.lastUpdated;
  const heartbeatDate = heartbeatTs?.toDate();
  const isStale = heartbeatDate && (now - heartbeatDate.getTime() > 120000); // 2 mins
  const isOffline = room.deviceStatus === "offline" || isStale;

  const status =
    isOffline
      ? "offline"
      : room.count === 0
        ? "available"
        : room.count >= maxOcc
          ? "full"
          : "occupied";

  const borderColor =
    status === "offline"
      ? "border-gray-300"
      : status === "full"
        ? "border-red-300"
        : status === "occupied"
          ? "border-orange-300"
          : "border-green-300";

  function startEdit(e: React.MouseEvent) {
    e.stopPropagation();
    setInputVal(room.maxOccupancy !== undefined ? String(room.maxOccupancy) : "");
    setEditing(true);
  }

  async function saveEdit(e: React.MouseEvent | React.KeyboardEvent) {
    e.stopPropagation();
    const parsed = parseInt(inputVal, 10);
    if (isNaN(parsed) || parsed < 0) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await updateDoc(doc(db, "classrooms", room.roomId), {
        maxOccupancy: parsed,
      });
    } catch (err) {
      console.error("Failed to update maxOccupancy:", err);
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  function cancelEdit(e: React.MouseEvent | React.FocusEvent) {
    e.stopPropagation();
    setEditing(false);
  }

  async function handleDelete(e: React.MouseEvent) {
    e.stopPropagation();
    if (!window.confirm("Are you sure you want to delete this room? This action cannot be undone.")) {
      return;
    }
    
    setIsDeleting(true);
    try {
      await deleteDoc(doc(db, "classrooms", room.roomId));
    } catch (err) {
      console.error("Failed to delete room:", err);
      alert("Failed to delete the room. Check console for details.");
      setIsDeleting(false);
    }
  }

  return (
    <div
      className={`rounded-xl border-2 ${borderColor} bg-white p-5 shadow-sm transition-shadow hover:shadow-md ${onClick ? "cursor-pointer" : ""}`}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") onClick(); } : undefined}
    >
      {/* Header */}
      <div className="mb-3 flex items-start justify-between">
        <h3 className="text-lg font-semibold text-slate-800">
          {room.roomName}
        </h3>
        <div className="flex items-center gap-2">
          <StatusBadge
            status={status === "offline" ? "available" : status}
            deviceStatus={isOffline ? "offline" : room.deviceStatus}
          />
          {isAdmin && (
            <button
              onClick={handleDelete}
              disabled={isDeleting}
              className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-500 disabled:opacity-50 transition-colors"
              title="Delete Room"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Student count */}
      <div className="mb-4">
        <div className="flex items-baseline justify-between">
          <p className="text-3xl font-bold text-slate-900">{room.count}</p>
          {room.maxOccupancy !== undefined && (
            <p className="text-sm text-slate-400">
              / {room.maxOccupancy}
            </p>
          )}
        </div>
        <p className="mb-2 text-sm text-slate-500">students~</p>
        {room.maxOccupancy !== undefined && (
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className={`h-full rounded-full transition-all ${
                status === "offline"
                  ? "bg-gray-400"
                  : status === "full"
                    ? "bg-red-500"
                    : status === "occupied"
                      ? "bg-orange-400"
                      : "bg-green-400"
              }`}
              style={{ width: `${Math.min((room.count / room.maxOccupancy) * 100, 100)}%` }}
            />
          </div>
        )}
      </div>

      {/* Max occupancy row */}
      <div
        className="mb-3 flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm"
        onClick={(e) => e.stopPropagation()}
      >
        <span className="text-slate-500">Max occupancy</span>
        {editing ? (
          <div className="flex items-center gap-1">
            <input
              autoFocus
              type="number"
              min={0}
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveEdit(e);
                if (e.key === "Escape") { e.stopPropagation(); setEditing(false); }
              }}
              onBlur={(e) => cancelEdit(e)}
              className="w-16 rounded border border-slate-300 px-1 py-0.5 text-right text-slate-800 focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            <button
              onMouseDown={saveEdit}
              disabled={saving}
              className="rounded px-2 py-0.5 text-xs font-medium text-blue-600 hover:bg-blue-50 disabled:opacity-50"
            >
              {saving ? "…" : "Save"}
            </button>
          </div>
        ) : isAdmin ? (
          <button
            onClick={startEdit}
            className="flex items-center gap-1 rounded px-2 py-0.5 text-slate-700 hover:bg-slate-200"
            title="Click to edit"
          >
            <span className="font-semibold">
              {room.maxOccupancy !== undefined ? room.maxOccupancy : "—"}
            </span>
            <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536M9 13l6.586-6.586a2 2 0 112.828 2.828L11.828 15.828a2 2 0 01-1.414.586H9v-2a2 2 0 01.586-1.414z" />
            </svg>
          </button>
        ) : (
          <span className="font-semibold px-2 py-0.5 text-slate-700">
            {room.maxOccupancy !== undefined ? room.maxOccupancy : "—"}
          </span>
        )}
      </div>

      {/* Heatmap mini preview — only shown when data is available */}
      {room.heatmap && (
        <div className="mb-3 border-t border-slate-100 pt-3" onClick={(e) => e.stopPropagation()}>
          <HeatmapMini heatmap={room.heatmap} />
        </div>
      )}

      {/* Footer meta */}
      <div className="flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-400">
        <span>ID: {room.roomId}</span>
        <span>Updated: {formatTime(room.lastUpdated)}</span>
      </div>
    </div>
  );
}
