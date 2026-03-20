import type { Classroom } from "../types";
import { ClassroomCard } from "./ClassroomCard";

interface ClassroomGridProps {
  classrooms: Classroom[];
  onSelect?: (room: Classroom) => void;
  isAdmin?: boolean;
}

export function ClassroomGrid({ classrooms, onSelect, isAdmin }: ClassroomGridProps) {
  if (classrooms.length === 0) {
    return (
      <div className="py-20 text-center text-slate-500">
        <p className="text-lg font-medium">No classrooms found</p>
        <p className="mt-1 text-sm">
          Make sure the bridge script is running and publishing data to
          Firestore.
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {classrooms.map((room) => (
        <ClassroomCard
          key={room.roomId}
          room={room}
          isAdmin={isAdmin}
          onClick={onSelect ? () => onSelect(room) : undefined}
        />
      ))}
    </div>
  );
}
