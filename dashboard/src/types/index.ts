import { Timestamp } from "firebase/firestore";

export interface Classroom {
  roomId: string;
  roomName: string;
  occupied: boolean;
  count: number;
  lastUpdated: Timestamp | null;
  deviceStatus: "online" | "offline" | "unknown";
  picoTimestamp?: number;
}
