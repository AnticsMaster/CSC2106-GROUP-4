interface StatusBadgeProps {
    status: "available" | "occupied" | "full";
    deviceStatus: "online" | "offline" | "unknown";
}

export function StatusBadge({ status, deviceStatus }: StatusBadgeProps) {
    if (deviceStatus === "offline") {
        return (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-200 px-3 py-1 text-xs font-semibold text-gray-600">
                <span className="h-2 w-2 rounded-full bg-gray-400" />
                Offline
            </span>
        );
    }

    if (status === "full") {
        return (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-red-100 px-3 py-1 text-xs font-semibold text-red-700">
                <span className="h-2 w-2 rounded-full bg-red-500" />
                Full
            </span>
        );
    }

    if (status === "occupied") {
        return (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-orange-100 px-3 py-1 text-xs font-semibold text-orange-700">
                <span className="h-2 w-2 rounded-full bg-orange-500" />
                Occupied
            </span>
        );
    }

    return (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-green-100 px-3 py-1 text-xs font-semibold text-green-700">
            <span className="h-2 w-2 rounded-full bg-green-500" />
            Available
        </span>
    );
}
