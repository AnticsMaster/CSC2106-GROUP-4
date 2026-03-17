import { useState } from "react";
import { doc, updateDoc } from "firebase/firestore";
import { db } from "../lib/firebase";
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
  onClick?: () => void;
}

export function ClassroomCard({ room, onClick }: ClassroomCardProps) {
  const [editing, setEditing] = useState(false);
  const [inputVal, setInputVal] = useState("");
  const [saving, setSaving] = useState(false);

  const borderColor =
    room.deviceStatus === "offline"
      ? "border-gray-300"
      : room.occupied
        ? "border-red-300"
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
        ) : (
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
        )}
      </div>

      {/* Footer meta */}
      <div className="flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-400">
        <span>ID: {room.roomId}</span>
        <span>Updated: {formatTime(room.lastUpdated)}</span>
      </div>
    </div>
  );
}
