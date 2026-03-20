import { useMemo } from "react";
import { useOccupancyHistory } from "../hooks/useOccupancyHistory";
import { generateForecast, predictOccupancy } from "../lib/prediction";
import type { Classroom } from "../types";
import { OccupancyChart } from "./OccupancyChart";
import { HeatmapGrid } from "./HeatmapGrid";
import { PredictionBadge } from "./PredictionBadge";
import { StatusBadge } from "./StatusBadge";

interface ClassroomDetailProps {
    room: Classroom;
    onClose: () => void;
}

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

export function ClassroomDetail({ room, onClose }: ClassroomDetailProps) {
    const { data: history, loading, error } = useOccupancyHistory(room.roomId);

    const prediction = useMemo(() => predictOccupancy(history), [history]);

    const forecast = useMemo(() => {
        if (!prediction) return [];
        return generateForecast(history, prediction);
    }, [history, prediction]);

    // Stats from history
    const stats = useMemo(() => {
        if (history.length === 0) return null;
        const counts = history.map(p => p.count);
        const avg = counts.reduce((a, b) => a + b, 0) / counts.length;
        const peak = Math.max(...counts);
        const min = Math.min(...counts);
        return {
            avg: Math.round(avg),
            peak,
            min,
            dataPoints: history.length,
        };
    }, [history]);

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
            <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl" onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
                    <div>
                        <h2 className="text-xl font-bold text-slate-800">{room.roomName}</h2>
                        <p className="mt-0.5 text-sm text-slate-400">ID: {room.roomId}</p>
                    </div>
                    <div className="flex items-center gap-3">
                        <StatusBadge
                            status={
                                room.count === 0
                                    ? "available"
                                    : room.count >= (room.maxOccupancy ?? Infinity)
                                      ? "full"
                                      : "occupied"
                            }
                            deviceStatus={room.deviceStatus}
                        />
                        <button
                            onClick={onClose}
                            className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
                            aria-label="Close"
                        >
                            <svg
                                xmlns="http://www.w3.org/2000/svg"
                                className="h-5 w-5"
                                fill="none"
                                viewBox="0 0 24 24"
                                stroke="currentColor"
                                strokeWidth={2}
                            >
                                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                </div>

                {/* Body */}
                <div className="px-6 py-5">
                    {/* Current status row */}
                    <div className="mb-5 flex flex-wrap gap-6">
                        <div>
                            <p className="text-sm text-slate-500">Current Count</p>
                            <p className="text-3xl font-bold text-slate-900">{room.count}</p>
                        </div>
                        <div>
                            <p className="text-sm text-slate-500">Last Updated</p>
                            <p className="text-lg font-semibold text-slate-700">{formatTime(room.lastUpdated)}</p>
                        </div>
                        {stats && (
                            <>
                                <div>
                                    <p className="text-sm text-slate-500">Avg</p>
                                    <p className="text-lg font-semibold text-slate-700">{stats.avg}</p>
                                </div>
                                <div>
                                    <p className="text-sm text-slate-500">Peak</p>
                                    <p className="text-lg font-semibold text-red-600">{stats.peak}</p>
                                </div>
                                <div>
                                    <p className="text-sm text-slate-500">Min</p>
                                    <p className="text-lg font-semibold text-green-600">{stats.min}</p>
                                </div>
                            </>
                        )}
                    </div>

                    {/* Error */}
                    {error && (
                        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                            <p className="font-semibold">Failed to load history</p>
                            <p className="mt-1 text-xs break-all">{error}</p>
                            {error.includes("index") && (
                                <p className="mt-2 text-xs text-red-600">
                                    This query requires a Firestore composite index. Check the browser console for a
                                    direct link to create it.
                                </p>
                            )}
                        </div>
                    )}

                    {/* Heatmap */}
                    <div className="mb-5">
                        <HeatmapGrid heatmap={room.heatmap} />
                    </div>

                    {/* Chart */}
                    <div className="mb-4">
                        <h3 className="mb-2 text-sm font-semibold text-slate-600">
                            Occupancy History
                            {forecast.length > 0 && <span className="ml-2 font-normal text-amber-600">+ Forecast</span>}
                        </h3>
                        <OccupancyChart history={history} forecast={forecast} loading={loading} />
                    </div>

                    {/* Prediction */}
                    <PredictionBadge prediction={prediction} />

                    {stats && <p className="mt-3 text-xs text-slate-400">Based on {stats.dataPoints} data points</p>}
                </div>
            </div>
        </div>
    );
}
