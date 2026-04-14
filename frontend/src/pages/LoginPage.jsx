import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login, register } from "../api";
import { notifyError, notifySuccess } from "../utils/toast";

export default function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    const normalizedEmail = email.trim().toLowerCase();

    if (!normalizedEmail || !password || (mode === "register" && !name.trim())) {
      notifyError(mode === "register" ? "Name, email and password are required." : "Email and password are required.");
      return;
    }

    if (mode === "register" && password !== confirmPassword) {
      notifyError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      if (mode === "register") {
        await register(name.trim(), normalizedEmail, password);
        notifySuccess("Account created successfully. Signing you in...");
      }
      const payload = await login(normalizedEmail, password);
      localStorage.setItem("jarvis_email", payload.email || normalizedEmail);
      localStorage.setItem("jarvis_name", payload.name || name.trim() || normalizedEmail);
      navigate("/analysis", { replace: true });
    } catch (err) {
      notifyError(err?.message || "Could not complete authentication.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#0e0e0e] px-4 py-10 text-[#d7d9e1]">
      <style>{`
        @keyframes loginFloatA {
          0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
          50% { transform: translate3d(42px, 24px, 0) scale(1.06); }
        }

        @keyframes loginFloatB {
          0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
          50% { transform: translate3d(-38px, -20px, 0) scale(1.08); }
        }

        @keyframes loginGlowPulse {
          0%, 100% { opacity: 0.32; transform: scale(1); }
          50% { opacity: 0.55; transform: scale(1.1); }
        }
      `}</style>

      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_17%_12%,rgba(96,125,255,0.17),transparent_38%),radial-gradient(circle_at_84%_86%,rgba(34,202,255,0.11),transparent_36%),linear-gradient(135deg,rgba(167,165,255,0.07)_0%,rgba(100,94,251,0.02)_58%,transparent_100%)]" />
      <div
        className="pointer-events-none absolute -left-24 top-[-32px] h-80 w-80 rounded-full bg-[radial-gradient(circle,rgba(110,124,255,0.32)_0%,rgba(110,124,255,0)_70%)] blur-3xl"
        style={{ animation: "loginFloatA 14s ease-in-out infinite" }}
      />
      <div
        className="pointer-events-none absolute -bottom-16 right-[-70px] h-[22rem] w-[22rem] rounded-full bg-[radial-gradient(circle,rgba(0,202,240,0.2)_0%,rgba(0,202,240,0)_70%)] blur-3xl"
        style={{ animation: "loginFloatB 16s ease-in-out infinite" }}
      />
      <div
        className="pointer-events-none absolute left-1/2 top-[34%] h-44 w-44 -translate-x-1/2 rounded-full bg-[radial-gradient(circle,rgba(167,165,255,0.2)_0%,rgba(167,165,255,0)_72%)] blur-2xl"
        style={{ animation: "loginGlowPulse 10s ease-in-out infinite" }}
      />

      <div className="relative mx-auto flex max-w-6xl flex-col gap-10 lg:flex-row lg:items-center lg:justify-between">
        <div className="max-w-xl pt-8 text-slate-100 lg:pt-0">
          <span className="inline-flex rounded-full border border-[rgba(167,165,255,0.28)] bg-[rgba(38,38,38,0.52)] px-4 py-1 text-xs uppercase tracking-[0.3em] text-slate-300">
            Login To Continue
          </span>
          <h1 className="mt-6 text-5xl font-semibold leading-tight sm:text-6xl">
            Continue your
            <span className="bg-gradient-to-r from-[#34c9ff] to-[#a7a5ff] bg-clip-text text-transparent"> adaptive </span>
            learning flow.
          </h1>
          <p className="mt-5 text-base leading-7 text-slate-300">
            Access your AI Prepare workspace, upload notes, and let CareerPilot AI ask focused questions from your study material.
          </p>
        </div>

        <div className="w-full max-w-md rounded-[32px] border border-[rgba(167,165,255,0.24)] bg-[rgba(19,19,19,0.92)] p-8 shadow-[0_24px_54px_rgba(2,6,20,0.55)] backdrop-blur-xl">
          <div className="mb-6 flex rounded-2xl border border-[rgba(167,165,255,0.22)] bg-[#201f1f] p-1">
            <button
              type="button"
              onClick={() => setMode("login")}
              className={`flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition ${mode === "login" ? "bg-[linear-gradient(135deg,#a7a5ff_0%,#645efb_100%)] text-white shadow-[0_8px_20px_rgba(100,94,251,0.38)]" : "text-slate-400"}`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => setMode("register")}
              className={`flex-1 rounded-xl px-4 py-2 text-sm font-semibold transition ${mode === "register" ? "bg-[linear-gradient(135deg,#a7a5ff_0%,#645efb_100%)] text-white shadow-[0_8px_20px_rgba(100,94,251,0.38)]" : "text-slate-400"}`}
            >
              Create account
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4 text-slate-100">
            {mode === "register" && (
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-[0.22em] text-white">Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Your nickname"
                  autoComplete="nickname"
                  className="w-full rounded-2xl border border-[rgba(167,165,255,0.22)] bg-[#201f1f] px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-[#a7a5ff]"
                />
              </div>
            )}
            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-[0.22em] text-white">Email</label>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
                className="w-full rounded-2xl border border-[rgba(167,165,255,0.22)] bg-[#201f1f] px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-[#a7a5ff]"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-[0.22em] text-white">Password</label>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="enter your password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                className="w-full rounded-2xl border border-[rgba(167,165,255,0.22)] bg-[#201f1f] px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-[#a7a5ff]"
              />
            </div>

            {mode === "register" && (
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-[0.22em] text-white">Confirm Password</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  placeholder="confirm your password"
                  autoComplete="new-password"
                  className="w-full rounded-2xl border border-[rgba(167,165,255,0.22)] bg-[#201f1f] px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-[#a7a5ff]"
                />
              </div>
            )}
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-2xl bg-[linear-gradient(135deg,#34c9ff_0%,#3a7bfd_100%)] px-4 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-60"
            >
              {loading ? (mode === "login" ? "Signing in..." : "Creating account...") : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          <div className="mt-5 flex items-center justify-between text-sm text-slate-400">
            <button type="button" onClick={() => { setMode(mode === "login" ? "register" : "login"); }} className="font-medium text-[#34c9ff] hover:text-[#7edcff]">
              {mode === "login" ? "Need an account? Create one" : "Already have an account? Sign in"}
            </button>
            <button type="button" onClick={() => navigate("/")} className="hover:text-slate-200">
              Back to home
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

