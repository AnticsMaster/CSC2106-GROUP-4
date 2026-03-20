import { signOut } from "firebase/auth";
import type { User } from "firebase/auth";
import { auth } from "../lib/firebase";

interface NavbarProps {
  user: User | null;
  onLoginClick: () => void;
}

export function Navbar({ user, onLoginClick }: NavbarProps) {
  const handleLogout = async () => {
    try {
      await signOut(auth);
    } catch (err) {
      console.error("Logout error", err);
    }
  };

  return (
    <header className="bg-slate-800 text-white shadow-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
        <h1 className="text-xl font-bold tracking-tight">
          Classroom Availability Tracker
        </h1>
        <div className="flex items-center gap-4">
          {user ? (
            <div className="flex items-center gap-3">
              <span className="text-sm text-slate-300">Admin</span>
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
