import { Navbar } from "./components/Navbar";
import { ClassroomGrid } from "./components/ClassroomGrid";
import { useClassrooms } from "./hooks/useClassrooms";

function App() {
  const { classrooms, loading, error } = useClassrooms();

  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />

      <main className="mx-auto max-w-6xl px-4 py-8">
        {/* Summary bar */}
        <div className="mb-6 flex flex-wrap items-center gap-4 text-sm text-slate-600">
          <span>
            Total rooms:{" "}
            <strong className="text-slate-900">{classrooms.length}</strong>
          </span>
          <span>
            Occupied:{" "}
            <strong className="text-red-600">
              {classrooms.filter((r) => r.occupied).length}
            </strong>
          </span>
          <span>
            Available:{" "}
            <strong className="text-green-600">
              {
                classrooms.filter(
                  (r) => !r.occupied && r.deviceStatus !== "offline",
                ).length
              }
            </strong>
          </span>
          <span>
            Offline:{" "}
            <strong className="text-gray-500">
              {classrooms.filter((r) => r.deviceStatus === "offline").length}
            </strong>
          </span>
        </div>

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

        {!loading && !error && <ClassroomGrid classrooms={classrooms} />}
      </main>
    </div>
  );
}

export default App;
