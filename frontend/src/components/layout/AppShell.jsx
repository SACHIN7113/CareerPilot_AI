import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  FiBarChart2,
  FiBookOpen,
  FiFileText,
  FiHelpCircle,
  FiLogOut,
  FiMenu,
  FiPlusCircle,
  FiSettings,
  FiClock,
  FiUser,
  FiX,
} from "react-icons/fi";
import { RiRobot2Line } from "react-icons/ri";

import { setToken } from "../../api";

const navItems = [
  { to: "/analysis", label: "Analysis", icon: FiFileText },
  { to: "/documents", label: "Documents", icon: FiBookOpen },
  { to: "/aiPrepare", label: "AI Prepare", icon: FiBarChart2 },
  { to: "/history", label: "History", icon: FiClock },
];

export default function AppShell({ title, subtitle, fullBleed = false, darkShell = true, headerActions, onStartNewSession, children }) {
  const navigate = useNavigate();
  const name = localStorage.getItem("jarvis_name") || "Learner";
  const email = localStorage.getItem("jarvis_email") || "learner@example.com";

  const [profileOpen, setProfileOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const profileRef = useRef(null);

  useEffect(() => {
    function handleOutside(event) {
      if (!profileRef.current) return;
      if (!profileRef.current.contains(event.target)) {
        setProfileOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  function handleLogout() {
    setToken("");
    localStorage.removeItem("jarvis_name");
    localStorage.removeItem("jarvis_email");
    navigate("/", { replace: true });
  }

  function handleStartSessionClick() {
    navigate("/aiPrepare");
    if (typeof onStartNewSession === "function") {
      onStartNewSession();
    }
    setSidebarOpen(false);
  }

  const rootTheme = darkShell ? "bg-[#0e0e0e] text-[#d7d9e1]" : "bg-[var(--color-bg)] text-[var(--color-text)]";
  const glowTheme = darkShell
    ? "bg-[radial-gradient(circle_at_17%_12%,rgba(96,125,255,0.17),transparent_38%),radial-gradient(circle_at_84%_86%,rgba(34,202,255,0.11),transparent_36%),linear-gradient(135deg,rgba(167,165,255,0.07)_0%,rgba(100,94,251,0.02)_58%,transparent_100%)]"
    : "bg-[radial-gradient(circle_at_15%_10%,rgba(87,141,255,0.12),transparent_35%),radial-gradient(circle_at_85%_90%,rgba(52,211,153,0.12),transparent_35%)]";
  const userInitial = String(name || "L").trim().charAt(0).toUpperCase() || "L";

  return (
    <div
      className={`relative ${rootTheme} ${darkShell ? "app-shell-dark" : ""} ${
        fullBleed ? "h-screen overflow-hidden" : "min-h-screen"
      }`}
    >
      <div className={`pointer-events-none fixed inset-0 ${glowTheme}`} />

      <div className={`relative flex ${fullBleed ? "h-full" : "min-h-screen"}`}>
        {sidebarOpen && (
          <button
            type="button"
            aria-label="Close sidebar"
            onClick={() => setSidebarOpen(false)}
            className="fixed inset-0 z-30 bg-slate-900/30 backdrop-blur-[1px] lg:hidden"
          />
        )}

        <aside
          className={`fixed inset-y-0 left-0 z-40 w-64 px-4 py-5 backdrop-blur-2xl transition-transform duration-300 lg:sticky lg:top-0 lg:z-0 lg:h-screen lg:translate-x-0 lg:shadow-none ${
            darkShell
              ? "bg-[#131313]/90 shadow-[0_24px_60px_rgba(2,6,20,0.55)]"
              : "border-[var(--color-border)] bg-white/92 shadow-[0_24px_60px_rgba(15,23,42,0.16)]"
          } ${
            sidebarOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="flex h-full flex-col">
            <button
              type="button"
              onClick={() => {
                navigate("/analysis");
                setSidebarOpen(false);
              }}
              className={`mb-7 flex w-full items-center gap-3 rounded-2xl border px-3 py-3 text-left ${
                darkShell
                  ? "border-[rgba(167,165,255,0.2)] bg-[linear-gradient(135deg,rgba(42,80,170,0.55)_0%,rgba(39,66,140,0.48)_50%,rgba(30,50,115,0.44)_100%)]"
                  : "border-[var(--color-border)] bg-[var(--color-surface-muted)]"
              }`}
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[linear-gradient(145deg,#3a7bfd,#51a7ff)] text-white shadow-lg">
                <RiRobot2Line className="text-lg" />
              </span>
              <span className="min-w-0">
                <span className={`ui-shell-brand-name ${darkShell ? "text-slate-100" : "text-slate-900"}`}>CareerPilot AI</span>
                <span className={`ui-shell-brand-tagline ${darkShell ? "text-slate-400" : "text-[var(--color-muted)]"}`}>Adaptive Interview Coach</span>
              </span>
            </button>

            <nav className="space-y-1.5">
              {navItems.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    onClick={() => setSidebarOpen(false)}
                    className={({ isActive }) =>
                      `group ui-shell-nav flex items-center gap-3 rounded-2xl px-3 py-2.5 transition ${
                        isActive
                          ? "bg-[linear-gradient(90deg,rgba(255,255,255,0.14),rgba(255,255,255,0.06))] text-white shadow-[0_10px_24px_rgba(0,0,0,0.28)]"
                          : darkShell
                          ? "text-slate-400 hover:bg-[rgba(36,39,54,0.65)] hover:text-slate-200"
                          : "text-slate-600 hover:bg-[var(--color-surface-muted)] hover:text-slate-900"
                      }`
                    }
                  >
                    <Icon className="text-base" />
                    <span>{item.label}</span>
                  </NavLink>
                );
              })}
            </nav>

            <div className="mt-auto space-y-2.5">
              <button
                type="button"
                onClick={handleStartSessionClick}
                className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-[linear-gradient(135deg,#8f88ff_0%,#5f67ff_100%)] px-4 py-2.5 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(95,103,255,0.45)] transition hover:brightness-110"
              >
                <FiPlusCircle className="text-sm" />
                Start New Session
              </button>

              <button
                type="button"
                onClick={() => {
                  navigate("/settings");
                  setSidebarOpen(false);
                }}
                className={`inline-flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition ${
                  darkShell
                    ? "text-slate-500 hover:bg-[rgba(36,39,54,0.65)] hover:text-slate-300"
                    : "text-slate-700 hover:bg-[var(--color-surface-muted)]"
                }`}
              >
                <FiSettings className="text-sm" />
                Settings
              </button>

              <button
                type="button"
                onClick={() => {
                  if (typeof window !== "undefined") {
                    window.location.href = "mailto:support@careerpilot.ai";
                  }
                }}
                className={`inline-flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition ${
                  darkShell
                    ? "text-slate-500 hover:bg-[rgba(36,39,54,0.65)] hover:text-slate-300"
                    : "text-slate-700 hover:bg-[var(--color-surface-muted)]"
                }`}
              >
                <FiHelpCircle className="text-sm" />
                Support
              </button>

              <div
                className={`mt-1 flex items-center gap-3 rounded-2xl border px-3 py-2.5 ${
                  darkShell
                    ? "border-[rgba(167,165,255,0.16)] bg-[rgba(25,28,40,0.7)]"
                    : "border-[var(--color-border)] bg-[var(--color-surface)]"
                }`}
              >
                <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[linear-gradient(135deg,#34c9ff,#8f88ff)] text-xs font-semibold text-white">
                  {userInitial}
                </span>
                <span className="min-w-0">
                  <span className={`block truncate text-sm font-semibold ${darkShell ? "text-slate-100" : "text-slate-900"}`}>{name}</span>
                  <span className={`block truncate text-[11px] ${darkShell ? "text-slate-500" : "text-[var(--color-muted)]"}`}>{email}</span>
                </span>
              </div>
            </div>
          </div>
        </aside>

        <div className={`flex min-w-0 flex-1 flex-col ${fullBleed ? "h-full overflow-hidden" : ""}`}>
          <header
            className={`sticky top-0 z-20 px-4 py-4 backdrop-blur-xl sm:px-6 ${
              darkShell
                ? "bg-[#131313]/85"
                : "border-[var(--color-border)] bg-white/82"
            }`}
          >
            <div className="flex items-center justify-between gap-4">
              <div className="flex min-w-0 items-center gap-3">
                <button
                  type="button"
                  onClick={() => setSidebarOpen((prev) => !prev)}
                  className={`inline-flex h-10 w-10 items-center justify-center rounded-xl border lg:hidden ${
                    darkShell
                      ? "border-[rgba(167,165,255,0.2)] bg-[#201f1f] text-slate-300"
                      : "border-[var(--color-border)] bg-white text-slate-700"
                  }`}
                >
                  {sidebarOpen ? <FiX className="text-base" /> : <FiMenu className="text-base" />}
                </button>
                <div className="min-w-0">
                  <h1 className={`ui-shell-title ${darkShell ? "text-slate-100" : "text-slate-900"}`}>{title}</h1>
                  <p className={`ui-shell-subtitle ${darkShell ? "text-slate-400" : "text-[var(--color-muted)]"}`}>{subtitle}</p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {headerActions}
                <div className="relative" ref={profileRef}>
                  <button
                    type="button"
                    onClick={() => setProfileOpen((value) => !value)}
                    className={`inline-flex h-10 w-10 items-center justify-center rounded-xl border transition ${
                      darkShell
                        ? "border-[rgba(167,165,255,0.2)] bg-[rgba(38,38,38,0.65)] text-slate-300 hover:bg-[rgba(50,50,50,0.75)] hover:text-white"
                        : "border-[var(--color-border)] bg-white text-slate-700 hover:text-slate-900"
                    }`}
                  >
                    <FiUser className="text-sm" />
                  </button>

                  {profileOpen && (
                    <div
                      className={`absolute right-0 mt-2 w-56 rounded-2xl border p-2 ${
                        darkShell
                          ? "border-[rgba(167,165,255,0.22)] bg-[#1b1d29] shadow-[0_20px_40px_rgba(2,6,20,0.5)]"
                          : "border-[var(--color-border)] bg-white shadow-[0_20px_40px_rgba(15,23,42,0.16)]"
                      }`}
                    >
                      <div className={`rounded-xl px-3 py-2 ${darkShell ? "bg-[#201f1f]" : "bg-[var(--color-surface-muted)]"}`}>
                        <p className={`ui-shell-brand-name ${darkShell ? "text-slate-100" : "text-slate-900"}`}>{name}</p>
                        <p className={`ui-shell-brand-tagline ${darkShell ? "text-slate-400" : "text-[var(--color-muted)]"}`}>{email}</p>
                      </div>

                      <button
                        type="button"
                        onClick={() => {
                          setProfileOpen(false);
                          navigate("/settings");
                        }}
                        className={`mt-2 inline-flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition ${
                          darkShell
                            ? "text-slate-200 hover:bg-[#201f1f]"
                            : "text-slate-700 hover:bg-[var(--color-surface-muted)]"
                        }`}
                      >
                        <FiSettings className="text-sm" />
                        Settings
                      </button>
                      <button
                        type="button"
                        onClick={handleLogout}
                        className={`mt-1 inline-flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition ${
                          darkShell
                            ? "text-red-300 hover:bg-red-500/20"
                            : "text-red-700 hover:bg-red-50"
                        }`}
                      >
                        <FiLogOut className="text-sm" />
                        Logout
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </header>

          <main
            className={`${
              fullBleed ? "flex min-h-0 flex-1 flex-col overflow-hidden px-4 py-4 sm:px-6" : "px-4 py-6 sm:px-6"
            }`}
          >
            <div className={fullBleed ? "flex h-full min-h-0 flex-col" : "mx-auto w-full max-w-7xl"}>{children}</div>
          </main>
        </div>
      </div>
    </div>
  );
}

