import { useState, useEffect } from "react";
import { Navbar } from "./components/Navbar";
import { ClassroomGrid } from "./components/ClassroomGrid";
import { ClassroomDetail } from "./components/ClassroomDetail";
import { Login } from "./components/Login";
import { DeviceHealth } from "./components/DeviceHealth";
import { useClassrooms } from "./hooks/useClassrooms";
import { useAuth } from "./hooks/useAuth";
import type { Classroom } from "./types";

function App() {
  const { classrooms, loading, error } = useClassrooms();
  const { user } = useAuth();
  const [selectedRoom, setSelectedRoom] = useState<Classroom | null>(null);
  const [showLogin, setShowLogin] = useState(false);
  const [currentView, setCurrentView] = useState<"dashboard" | "health">("dashboard");
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(timer);
  }, []);

  // Reset view if user logs out
  useEffect(() => {
    if (!user) {
      setCurrentView("dashboard");
    }
  }, [user]);

  // Keep selectedRoom in sync with live data
  const liveSelectedRoom = selectedRoom
    ? classrooms.find((r) => r.roomId === selectedRoom.roomId) ?? selectedRoom
    : null;

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar 
        user={user} 
        onLoginClick={() => setShowLogin(true)} 
        currentView={currentView}
        onViewChange={setCurrentView}
      />

      <main className="mx-auto max-w-6xl px-4 py-8">
        {showLogin && !user ? (
          <Login 
            onSuccess={() => setShowLogin(false)} 
            onCancel={() => setShowLogin(false)} 
          />
        ) : (
          <>
            {currentView === "dashboard" ? (
              <>
                {/* Summary bar */}
                <div className="mb-6 flex flex-wrap items-center gap-4 text-sm text-slate-600">
                  <span>
                    Total rooms:{" "}
                    <strong className="text-slate-900">{classrooms.length}</strong>
                  </span>
                  <span>
                    Occupied:{" "}
                    <strong className="text-orange-500">
                      {
                        classrooms.filter((r) => {
                          const heartbeatTs = r.lastSeen || r.lastUpdated;
                          const heartbeatDate = heartbeatTs?.toDate();
                          const isStale = heartbeatDate && now - heartbeatDate.getTime() > 120000;
                          return !(r.deviceStatus === "offline" || isStale) && r.count > 0;
                        }).length
                      }
                    </strong>
                  </span>
                  <span>
                    Available:{" "}
                    <strong className="text-green-600">
                      {
                        classrooms.filter((r) => {
                          const heartbeatTs = r.lastSeen || r.lastUpdated;
                          const heartbeatDate = heartbeatTs?.toDate();
                          const isStale = heartbeatDate && now - heartbeatDate.getTime() > 120000;
                          return !(r.deviceStatus === "offline" || isStale) && r.count === 0;
                        }).length
                      }
                    </strong>
                  </span>
                  <span>
                    Offline:{" "}
                    <strong className="text-gray-500">
                      {
                        classrooms.filter((r) => {
                          const heartbeatTs = r.lastSeen || r.lastUpdated;
                          const heartbeatDate = heartbeatTs?.toDate();
                          const isStale = heartbeatDate && now - heartbeatDate.getTime() > 120000;
                          return r.deviceStatus === "offline" || isStale;
                        }).length
                      }
                    </strong>
                  </span>
                </div>

                {/* Hint */}
                {!loading && !error && classrooms.length > 0 && (
                  <p className="mb-4 text-xs text-slate-400">
                    Click a room card to view occupancy history and predictions.
                  </p>
                )}

                {/* Content */}
                {loading && (
                  <p className="py-20 text-center text-slate-400">
                    Loading classrooms...
                  </p>
                )}

                {error && (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                    <p className="font-semibold">Firestore error</p>
                    <p>{error}</p>
                  </div>
                )}

                {!loading && !error && (
                  <ClassroomGrid
                    classrooms={classrooms}
                    isAdmin={!!user}
                    onSelect={setSelectedRoom}
                  />
                )}
              </>
            ) : (
              <DeviceHealth classrooms={classrooms} />
            )}
          </>
        )}
      </main>

      {/* Detail modal */}
      {liveSelectedRoom && (
        <ClassroomDetail
          room={liveSelectedRoom}
          onClose={() => setSelectedRoom(null)}
        />
      )}
    </div>
  );
}

export default App;
