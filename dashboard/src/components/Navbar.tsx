import { signOut } from "firebase/auth";
import type { User } from "firebase/auth";
import { auth } from "../lib/firebase";

interface NavbarProps {
  user: User | null;
  onLoginClick: () => void;
  currentView?: "dashboard" | "health";
  onViewChange?: (view: "dashboard" | "health") => void;
}

export function Navbar({ user, onLoginClick, currentView, onViewChange }: NavbarProps) {
  const handleLogout = async () => {
    try {
      await signOut(auth);
    } catch (err) {
      console.error("Logout error", err);
    }
  };

  return (
    <header className="bg-slate-800 text-white shadow-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4">
        <div className="flex items-center gap-8 py-4">
          <h1 className="text-xl font-bold tracking-tight">
            Classroom Availability Tracker
          </h1>
          
          {user && onViewChange && (
            <nav className="hidden md:flex items-center gap-1 self-stretch">
              <button
                onClick={() => onViewChange("dashboard")}
                className={`flex items-center gap-2 px-3 self-stretch transition-colors border-b-2 font-medium text-sm ${
                  currentView === "dashboard"
                    ? "border-blue-500 text-white"
                    : "border-transparent text-slate-400 hover:text-slate-200"
                }`}
              >
                Dashboard
              </button>
              <button
                onClick={() => onViewChange("health")}
                className={`flex items-center gap-2 px-3 self-stretch transition-colors border-b-2 font-medium text-sm ${
                  currentView === "health"
                    ? "border-blue-500 text-white"
                    : "border-transparent text-slate-400 hover:text-slate-200"
                }`}
              >
                Device Health
              </button>
            </nav>
          )}
        </div>

        <div className="flex items-center gap-4 py-4">
          {user ? (
            <div className="flex items-center gap-3">
              <span className="hidden sm:inline text-xs bg-slate-700 px-2 py-1 rounded text-slate-300 font-bold uppercase tracking-wider">Admin</span>
              <button
                onClick={handleLogout}
                className="rounded bg-slate-700 px-3 py-1.5 text-sm font-medium hover:bg-slate-600"
              >
                Logout
              </button>
            </div>
          ) : (
            <button
              onClick={onLoginClick}
              className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium hover:bg-blue-500"
            >
              Admin Login
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
