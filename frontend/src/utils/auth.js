const TOKEN_KEY = "jarvis_token";
const EMAIL_KEY = "jarvis_email";
const NAME_KEY = "jarvis_name";

function decodeTokenPayload(token) {
  try {
    const parts = String(token || "").split(".");
    if (parts.length < 2) return null;

    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const payloadJson = atob(padded);
    return JSON.parse(payloadJson);
  } catch {
    return null;
  }
}
export function isTokenExpired(token) {
  const payload = decodeTokenPayload(token);
  const exp = Number(payload?.exp);
  if (!Number.isFinite(exp) || exp <= 0) return true;
  return Date.now() >= exp * 1000;
}

export function clearAuthStorage() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EMAIL_KEY);
  localStorage.removeItem(NAME_KEY);
}

export function getValidStoredToken() {
  if (typeof window === "undefined") return "";

  const token = localStorage.getItem(TOKEN_KEY) || "";
  if (!token) return "";

  if (isTokenExpired(token)) {
    clearAuthStorage();
    return "";
  }

  return token;
}

export function hasValidSession() {
  return Boolean(getValidStoredToken());
}
