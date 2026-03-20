import type { HeatmapData } from "../types";

// ── Score → visual style mapping ──────────────────────────────────────────────
const ZONE_STYLES: Record<
    number,
    { bg: string; ring: string; dot: string; label: string }
> = {
    0: { bg: "bg-slate-100",  ring: "ring-slate-200",  dot: "bg-slate-300",  label: "None"   },
    1: { bg: "bg-green-100",  ring: "ring-green-200",  dot: "bg-green-500",  label: "Low"    },
    2: { bg: "bg-amber-100",  ring: "ring-amber-200",  dot: "bg-amber-500",  label: "Medium" },
    3: { bg: "bg-red-100",    ring: "ring-red-200",    dot: "bg-red-500",    label: "High"   },
};

// Zone grid positions (top-down):
//   Z1 (index 0) | Z2 (index 1)
//   Z3 (index 2) | Z4 (index 3)
const ZONE_NAMES = ["Zone 1", "Zone 2", "Zone 3", "Zone 4"];

interface ZoneCellProps {
    zoneName: string;
    score: number;
    mini?: boolean;
}

function ZoneCell({ zoneName, score, mini }: ZoneCellProps) {
    const style = ZONE_STYLES[score] ?? ZONE_STYLES[0];

    if (mini) {
        // Compact 2×2 used on the card
        return (
            <div
                className={`flex items-center justify-center rounded ${style.bg} ring-1 ${style.ring}`}
                title={`${zoneName}: ${style.label}`}
            >
                <span className={`h-2.5 w-2.5 rounded-full ${style.dot}`} />
            </div>
        );
    }

    // Full cell used in the detail modal
    return (
        <div
            className={`flex flex-col items-center justify-center gap-1 rounded-xl p-4 ring-1 ${style.bg} ${style.ring}`}
        >
            <span className={`h-3 w-3 rounded-full ${style.dot}`} />
            <p className="text-xs font-semibold text-slate-600">{zoneName}</p>
            <p className={`text-xs font-bold ${score === 0 ? "text-slate-400" : score === 1 ? "text-green-700" : score === 2 ? "text-amber-700" : "text-red-700"}`}>
                {style.label}
            </p>
        </div>
    );
}

// ── Legend ─────────────────────────────────────────────────────────────────────
function Legend() {
    return (
        <div className="flex flex-wrap gap-3 text-xs text-slate-500">
            {Object.entries(ZONE_STYLES).map(([score, s]) => (
                <span key={score} className="flex items-center gap-1">
                    <span className={`inline-block h-2 w-2 rounded-full ${s.dot}`} />
                    {s.label}
                </span>
            ))}
        </div>
    );
}

// ── Mini variant (used on ClassroomCard) ──────────────────────────────────────
interface HeatmapMiniProps {
    heatmap: HeatmapData;
}

export function HeatmapMini({ heatmap }: HeatmapMiniProps) {
    const zones = heatmap.zones.slice(0, 4);
    while (zones.length < 4) zones.push(0);

    return (
        <div>
            <p className="mb-1 text-xs font-medium text-slate-400">Zone activity</p>
            <div className="grid grid-cols-2 gap-1" style={{ height: "3rem" }}>
                {zones.map((score, i) => (
                    <ZoneCell key={i} zoneName={ZONE_NAMES[i]} score={score} mini />
                ))}
            </div>
        </div>
    );
}

// ── Full variant (used in ClassroomDetail) ────────────────────────────────────
interface HeatmapGridProps {
    heatmap: HeatmapData | undefined;
}

export function HeatmapGrid({ heatmap }: HeatmapGridProps) {
    if (!heatmap) {
        return (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-400">
                No heatmap data yet — waiting for first 30-second interval.
            </div>
        );
    }

    const zones = heatmap.zones.slice(0, 4);
    while (zones.length < 4) zones.push(0);

    function formatTs(ts: HeatmapData["lastUpdated"]): string {
        if (!ts) return "";
        try {
            return ts.toDate().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        } catch {
            return "";
        }
    }

    return (
        <div>
            <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-600">Zone Activity Heatmap</h3>
                {heatmap.lastUpdated && (
                    <span className="text-xs text-slate-400">Updated {formatTs(heatmap.lastUpdated)}</span>
                )}
            </div>

            {/* 2×2 zone grid */}
            <div className="mb-3 grid grid-cols-2 gap-2">
                {zones.map((score, i) => (
                    <ZoneCell key={i} zoneName={ZONE_NAMES[i]} score={score} />
                ))}
            </div>

            {/* Layout legend */}
            <p className="mb-2 text-xs text-slate-400">
                Layout (top-down view): &nbsp;
                <span className="font-mono">GP0 | GP6</span> / <span className="font-mono">GP8 | GP26</span>
            </p>

            <Legend />
        </div>
    );
}
