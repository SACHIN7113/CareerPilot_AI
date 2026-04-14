import { useEffect, useMemo, useState } from "react";
import { FiBell, FiCheckCircle, FiKey, FiMonitor, FiShield, FiSmartphone } from "react-icons/fi";
import { useNavigate } from "react-router-dom";

import AppShell from "../components/layout/AppShell";
import { readDocumentUploadHistory, readPracticeStats } from "../utils/storage";
import { notifyError, notifyInfo, notifySuccess } from "../utils/toast";

const PREF_EMAIL_ALERTS_KEY = "jarvis_pref_email_alerts";
const PREF_PUBLIC_VISIBILITY_KEY = "jarvis_pref_public_visibility";
const RECENT_SESSIONS_KEY = "jarvis_recent_sessions_v1";

function detectBrowser(ua) {
  const text = String(ua || "").toLowerCase();
  if (text.includes("edg")) return "Edge";
  if (text.includes("chrome") && !text.includes("edg")) return "Chrome";
  if (text.includes("firefox")) return "Firefox";
  if (text.includes("safari") && !text.includes("chrome")) return "Safari";
  return "Browser";
}

function detectDevice(ua) {
  const text = String(ua || "").toLowerCase();
  if (text.includes("iphone")) return "iPhone";
  if (text.includes("android")) return "Android";
  if (text.includes("windows")) return "Windows PC";
  if (text.includes("mac")) return "Mac";
  if (text.includes("linux")) return "Linux";
  return "This device";
}

function readBooleanSetting(key, fallback) {
  const raw = localStorage.getItem(key);
  if (raw === "1") return true;
  if (raw === "0") return false;
  return fallback;
}

function formatRelativeTime(timestamp) {
  const time = Number(timestamp || 0);
  if (!time) return "No activity";

  const delta = Date.now() - time;
  if (delta < 60_000) return "Active now";
  if (delta < 3_600_000) return `Active ${Math.max(1, Math.floor(delta / 60_000))} min ago`;
  if (delta < 86_400_000) return `Active ${Math.max(1, Math.floor(delta / 3_600_000))} hr ago`;
  return `Active ${Math.max(1, Math.floor(delta / 86_400_000))} day ago`;
}

function getInitials(name) {
  const parts = String(name || "Learner")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2);
  if (!parts.length) return "L";
  return parts.map((part) => part.charAt(0).toUpperCase()).join("");
}

function buildCurrentSession() {
  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";
  const browser = detectBrowser(ua);
  const device = detectDevice(ua);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Local time";

  return {
    id: `current-${device}-${browser}`,
    signature: `${device}|${browser}|${timezone}`,
    device,
    browser,
    timezone,
    current: true,
    lastSeen: Date.now(),
  };
}

export default function SettingsPage() {
  const navigate = useNavigate();
  const email = localStorage.getItem("jarvis_email") || "";

  const [profileName, setProfileName] = useState(localStorage.getItem("jarvis_name") || "Learner");
  const [emailAlerts, setEmailAlerts] = useState(readBooleanSetting(PREF_EMAIL_ALERTS_KEY, true));
  const [publicVisibility, setPublicVisibility] = useState(readBooleanSetting(PREF_PUBLIC_VISIBILITY_KEY, false));
  const [recentSessions, setRecentSessions] = useState([]);
  const [stats, setStats] = useState(readPracticeStats());
  const [uploadHistory, setUploadHistory] = useState(readDocumentUploadHistory());

  useEffect(() => {
    setStats(readPracticeStats());
    setUploadHistory(readDocumentUploadHistory());

    const currentSession = buildCurrentSession();
    let stored = [];
    try {
      const raw = localStorage.getItem(RECENT_SESSIONS_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      stored = Array.isArray(parsed) ? parsed : [];
    } catch {
      stored = [];
    }

    const merged = [
      currentSession,
      ...stored
        .filter((item) => item?.signature && item.signature !== currentSession.signature)
        .slice(0, 4)
        .map((item) => ({ ...item, current: false })),
    ];

    setRecentSessions(merged);
    localStorage.setItem(
      RECENT_SESSIONS_KEY,
      JSON.stringify(merged.map(({ current, ...item }) => item).slice(0, 5))
    );
  }, []);

  const documentCount = Math.max(Number(stats.documentsUploaded || 0), uploadHistory.length);
  const memberTier = Number(stats.sessionsStarted || 0) >= 25 ? "Pro Member" : "Member";
  const usageBadge = documentCount >= 1 ? "Early Adopter" : "Getting Started";
  const lastActiveDocument = stats.lastDocumentTitle || uploadHistory[0]?.title || "No JD selected";

  const latestFeedback = useMemo(() => {
    const text = String(stats.lastFeedback || "").trim();
    if (!text) return "No recent feedback yet.";
    return text;
  }, [stats.lastFeedback]);

  function handleSaveProfile() {
    const trimmed = String(profileName || "").trim();
    if (!trimmed) {
      notifyError("Profile name cannot be empty.");
      return;
    }
    localStorage.setItem("jarvis_name", trimmed);
    setProfileName(trimmed);
    notifySuccess("Profile saved successfully.");
  }

  function handleToggleEmailAlerts() {
    setEmailAlerts((prev) => {
      const next = !prev;
      localStorage.setItem(PREF_EMAIL_ALERTS_KEY, next ? "1" : "0");
      return next;
    });
  }

  function handleTogglePublicVisibility() {
    setPublicVisibility((prev) => {
      const next = !prev;
      localStorage.setItem(PREF_PUBLIC_VISIBILITY_KEY, next ? "1" : "0");
      return next;
    });
  }

  function handleRevokeSession(sessionId) {
    const next = recentSessions.filter((item) => item.id !== sessionId);
    setRecentSessions(next);
    localStorage.setItem(
      RECENT_SESSIONS_KEY,
      JSON.stringify(next.map(({ current, ...item }) => item).slice(0, 5))
    );
    notifyInfo("Session removed from this device list.");
  }

  return (
    <AppShell title="Account Details" subtitle="Refine your profile and security settings for the Obsidian ecosystem." fullBleed>
      <div className="min-h-0 flex-1 overflow-y-auto pb-8">
        <div className="mx-auto w-full max-w-6xl space-y-5">
          <section className="rounded-3xl border border-[rgba(146,150,255,0.16)] bg-[rgba(22,24,33,0.82)] p-4 shadow-[0_20px_50px_rgba(2,8,26,0.35)] backdrop-blur-xl sm:p-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-4">
                <div className="relative">
                  <span className="inline-flex h-16 w-16 items-center justify-center rounded-full border border-[rgba(121,207,255,0.4)] bg-[linear-gradient(135deg,#155e75,#312e81)] text-lg font-semibold text-slate-100">
                    {getInitials(profileName)}
                  </span>
                  <span className="absolute -bottom-1 -right-1 inline-flex h-6 w-6 items-center justify-center rounded-full border border-[rgba(148,163,184,0.35)] bg-[#8f88ff] text-[10px] text-white">
                    <FiCheckCircle />
                  </span>
                </div>
                <div className="min-w-0">
                  <p className="truncate text-2xl font-semibold text-slate-100">{profileName}</p>
                  <p className="truncate text-xs uppercase tracking-[0.12em] text-slate-400">{email || "No email on file"}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <span className="rounded-full bg-[rgba(139,92,246,0.22)] px-3 py-1 text-[11px] font-semibold text-[#c8b8ff]">{memberTier}</span>
                    <span className="rounded-full bg-[rgba(6,182,212,0.2)] px-3 py-1 text-[11px] font-semibold text-[#8fe8ff]">{usageBadge}</span>
                  </div>
                </div>
              </div>

              <button
                type="button"
                onClick={handleSaveProfile}
                className="inline-flex items-center justify-center rounded-xl bg-[linear-gradient(135deg,#9a8fff_0%,#6b76ff_100%)] px-5 py-2.5 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(95,103,255,0.45)] transition hover:brightness-110"
              >
                Save Profile
              </button>
            </div>
          </section>

          <div className="grid gap-5 lg:grid-cols-2">
            <section className="rounded-3xl border border-[rgba(146,150,255,0.12)] bg-[rgba(26,26,30,0.8)] p-5 backdrop-blur-xl">
              <div className="mb-4 flex items-center gap-2 text-slate-200">
                <FiBell className="text-sm text-[#b4a9ff]" />
                <h2 className="text-lg font-semibold">Preferences</h2>
              </div>

              <div className="space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-100">Email Alerts</p>
                    <p className="text-xs text-slate-400">Weekly digest and AI insight updates</p>
                  </div>
                  <button
                    type="button"
                    onClick={handleToggleEmailAlerts}
                    className={`relative h-6 w-11 rounded-full transition ${
                      emailAlerts ? "bg-[linear-gradient(90deg,#9a8fff,#7e89ff)]" : "bg-slate-700"
                    }`}
                    aria-pressed={emailAlerts}
                    aria-label="Toggle email alerts"
                  >
                    <span
                      className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${
                        emailAlerts ? "left-[22px]" : "left-0.5"
                      }`}
                    />
                  </button>
                </div>

                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-100">Public Visibility</p>
                    <p className="text-xs text-slate-400">Show profile progress in community mode</p>
                  </div>
                  <button
                    type="button"
                    onClick={handleTogglePublicVisibility}
                    className={`relative h-6 w-11 rounded-full transition ${
                      publicVisibility ? "bg-[linear-gradient(90deg,#9a8fff,#7e89ff)]" : "bg-slate-700"
                    }`}
                    aria-pressed={publicVisibility}
                    aria-label="Toggle public visibility"
                  >
                    <span
                      className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${
                        publicVisibility ? "left-[22px]" : "left-0.5"
                      }`}
                    />
                  </button>
                </div>
              </div>
            </section>

            <section className="rounded-3xl border border-[rgba(146,150,255,0.12)] bg-[rgba(26,26,30,0.8)] p-5 backdrop-blur-xl">
              <div className="mb-4 flex items-center gap-2 text-slate-200">
                <FiShield className="text-sm text-[#b4a9ff]" />
                <h2 className="text-lg font-semibold">Security</h2>
              </div>

              <div className="space-y-2.5">
                <button
                  type="button"
                  onClick={() => navigate("/settings/password")}
                  className="flex w-full items-center justify-between rounded-xl border border-[rgba(148,163,184,0.2)] bg-[rgba(8,10,18,0.45)] px-3 py-2.5 text-left transition hover:border-[rgba(143,136,255,0.45)]"
                >
                  <span className="inline-flex items-center gap-2 text-sm font-medium text-slate-200">
                    <FiKey className="text-[13px] text-slate-400" />
                    Change Password
                  </span>
                  <span className="text-slate-500">›</span>
                </button>
              </div>

              <div className="mt-5 rounded-xl border border-[rgba(148,163,184,0.18)] bg-[rgba(8,10,18,0.45)] p-3">
                <p className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Last Active Context</p>
                <p className="mt-1 truncate text-sm font-semibold text-slate-100">{lastActiveDocument}</p>
              </div>
            </section>
          </div>

          <section className="rounded-3xl border border-[rgba(146,150,255,0.12)] bg-[rgba(15,17,24,0.82)] p-5 backdrop-blur-xl">
            <h2 className="text-lg font-semibold text-slate-100">Recent Sessions</h2>
            <p className="mt-1 text-xs text-slate-400">Real-time session details from this browser context.</p>

            <div className="mt-4 divide-y divide-[rgba(148,163,184,0.14)]">
              {recentSessions.map((session) => {
                const SessionIcon = /iphone|android/i.test(session.device || "") ? FiSmartphone : FiMonitor;
                return (
                  <div key={session.id} className="flex items-center justify-between gap-3 py-3">
                    <div className="min-w-0 flex items-center gap-3">
                      <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[rgba(143,136,255,0.2)] text-[#c9c2ff]">
                        <SessionIcon className="text-sm" />
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-100">{session.device}</p>
                        <p className="truncate text-xs text-slate-400">
                          {formatRelativeTime(session.lastSeen)} · {session.browser} · {session.timezone}
                        </p>
                      </div>
                    </div>

                    {session.current ? (
                      <span className="rounded-full bg-[rgba(167,165,255,0.14)] px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-[#bfb9ff]">
                        Current
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleRevokeSession(session.id)}
                        className="text-xs font-semibold text-slate-400 transition hover:text-red-300"
                      >
                        Revoke
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </div>
    </AppShell>
  );
}

