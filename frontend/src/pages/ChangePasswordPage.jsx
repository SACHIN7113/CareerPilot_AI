import { useState } from "react";
import { FiArrowLeft, FiShield } from "react-icons/fi";
import { useNavigate } from "react-router-dom";

import { changePassword } from "../api";
import AppShell from "../components/layout/AppShell";
import { notifyError, notifySuccess } from "../utils/toast";

export default function ChangePasswordPage() {
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();

    if (!currentPassword || !newPassword || !confirmPassword) {
      notifyError("Please fill all password fields.");
      return;
    }

    if (newPassword.length < 6) {
      notifyError("New password must be at least 6 characters.");
      return;
    }

    if (newPassword !== confirmPassword) {
      notifyError("New password and confirm password must match.");
      return;
    }

    if (currentPassword === newPassword) {
      notifyError("New password must be different from current password.");
      return;
    }

    setLoading(true);
    try {
      const payload = await changePassword(currentPassword, newPassword);
      notifySuccess(payload?.message || "Password updated successfully.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      navigate("/settings", { replace: true });
    } catch (err) {
      notifyError(err?.message || "Could not update password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AppShell
      title="Change Password"
      subtitle="Update your credentials securely for this account."
      fullBleed
    >
      <div className="min-h-0 flex-1 overflow-y-auto pb-8">
        <div className="mx-auto w-full max-w-2xl space-y-4 px-1">
          <button
            type="button"
            onClick={() => navigate("/settings")}
            className="inline-flex items-center gap-2 rounded-xl border border-[rgba(146,150,255,0.2)] bg-[rgba(22,24,33,0.55)] px-3 py-2 text-sm text-slate-300 transition hover:text-white"
          >
            <FiArrowLeft className="text-sm" />
            Back to Settings
          </button>

          <section className="rounded-3xl border border-[rgba(146,150,255,0.16)] bg-[rgba(22,24,33,0.82)] p-5 shadow-[0_20px_50px_rgba(2,8,26,0.35)] backdrop-blur-xl sm:p-6">
            <div className="mb-5 flex items-center gap-2 text-slate-100">
              <FiShield className="text-base text-[#b4a9ff]" />
              <h2 className="text-lg font-semibold">Security Check</h2>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-[0.18em] text-slate-300">
                  Current Password
                </label>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                  autoComplete="current-password"
                  className="w-full rounded-2xl border border-[rgba(167,165,255,0.22)] bg-[#201f1f] px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-[#a7a5ff]"
                  placeholder="Enter your current password"
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-[0.18em] text-slate-300">
                  New Password
                </label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  autoComplete="new-password"
                  className="w-full rounded-2xl border border-[rgba(167,165,255,0.22)] bg-[#201f1f] px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-[#a7a5ff]"
                  placeholder="Enter a new password"
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-[0.18em] text-slate-300">
                  Confirm New Password
                </label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  autoComplete="new-password"
                  className="w-full rounded-2xl border border-[rgba(167,165,255,0.22)] bg-[#201f1f] px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-[#a7a5ff]"
                  placeholder="Confirm your new password"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="mt-2 inline-flex w-full items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#34c9ff_0%,#3a7bfd_100%)] px-4 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-60"
              >
                {loading ? "Updating password..." : "Update Password"}
              </button>
            </form>
          </section>
        </div>
      </div>
    </AppShell>
  );
}
