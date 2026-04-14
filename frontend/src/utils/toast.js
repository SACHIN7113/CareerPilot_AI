import { toast } from "react-toastify";

const BASE_TOAST_OPTIONS = {
  style: {
    background: "rgba(14, 17, 32, 0.96)",
    color: "#d7d9e1",
    border: "1px solid rgba(122, 131, 255, 0.26)",
    backdropFilter: "blur(8px)",
  },
};

function normalizeToastMessage(message) {
  const text = String(message || "").trim();
  if (!text) return "";

  if (/request timed out|took too long/i.test(text)) {
    return "Server is taking longer than expected. Please try again in a few seconds.";
  }
  if (/failed to fetch|cannot connect|networkerror|network error/i.test(text)) {
    return "Unable to reach server. Check your connection and ensure backend is running.";
  }
  return text;
}

export function notifyError(message) {
  const normalized = normalizeToastMessage(message);
  if (!normalized) return;
  toast.error(normalized, {
    ...BASE_TOAST_OPTIONS,
    toastId: `error-${normalized}`,
  });
}

export function notifySuccess(message) {
  if (!message) return;
  toast.success(String(message), {
    ...BASE_TOAST_OPTIONS,
  });
}

export function notifyInfo(message) {
  if (!message) return;
  toast.info(String(message), {
    ...BASE_TOAST_OPTIONS,
  });
}
