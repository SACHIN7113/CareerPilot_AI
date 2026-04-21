const API_URL = String(
  import.meta.env.VITE_API_URL || "http://localhost:8000",
).replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 45000;
const inflightGetRequests = new Map();
const getResponseCache = new Map();

let accessToken = localStorage.getItem("jarvis_token") || "";

function clearSession() {
  accessToken = "";
  localStorage.removeItem("jarvis_token");
  localStorage.removeItem("jarvis_email");
  localStorage.removeItem("jarvis_name");
  inflightGetRequests.clear();
  getResponseCache.clear();
}

function invalidateGetCache(matchers = []) {
  if (!Array.isArray(matchers) || !matchers.length) {
    getResponseCache.clear();
    return;
  }

  for (const key of getResponseCache.keys()) {
    const path = key.startsWith("GET:") ? key.slice(4) : key;
    if (matchers.some((matcher) => path.startsWith(String(matcher)))) {
      getResponseCache.delete(key);
    }
  }
}

export function setToken(token) {
  accessToken = token || "";
  if (accessToken) {
    localStorage.setItem("jarvis_token", accessToken);
  } else {
    clearSession();
  }
}

function extractErrorMessage(payload, fallback = "Request failed") {
  if (!payload || typeof payload !== "object") {
    return fallback;
  }

  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail.trim();
  }

  if (Array.isArray(payload.detail) && payload.detail.length > 0) {
    const first = payload.detail[0];
    if (typeof first === "string" && first.trim()) {
      return first.trim();
    }
    if (first && typeof first.msg === "string" && first.msg.trim()) {
      return first.msg.trim();
    }
  }

  if (typeof payload.message === "string" && payload.message.trim()) {
    return payload.message.trim();
  }

  return fallback;
}

async function request(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const dedupeEnabled =
    method === "GET" && options.dedupe !== false && !options.signal;
  const dedupeKey = dedupeEnabled ? `${method}:${path}` : "";
  const cacheTtlMs = method === "GET" ? Number(options.cacheTtlMs || 0) : 0;
  const cacheEnabled = cacheTtlMs > 0 && !options.signal;

  if (cacheEnabled && dedupeKey) {
    const cached = getResponseCache.get(dedupeKey);
    if (cached && cached.expiresAt > Date.now()) {
      return cached.value;
    }
    if (cached) {
      getResponseCache.delete(dedupeKey);
    }
  }

  if (dedupeKey && inflightGetRequests.has(dedupeKey)) {
    return inflightGetRequests.get(dedupeKey);
  }

  const run = async () => {
    const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
    const allowRetry = options.retry ?? (method === "GET" || method === "HEAD");
    const retryCount = allowRetry ? (options.retryCount ?? 1) : 0;

    for (let attempt = 0; attempt <= retryCount; attempt += 1) {
      const controller = new AbortController();
      const timeoutId = setTimeout(
        () => controller.abort(),
        timeoutMs + attempt * 5000,
      );
      const headers = { ...(options.headers || {}) };
      if (accessToken) {
        headers.Authorization = `Bearer ${accessToken}`;
      }

      try {
        const response = await fetch(`${API_URL}${path}`, {
          ...options,
          headers,
          signal: options.signal || controller.signal,
        });

        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          if (response.status === 401 && path !== "/api/auth/login") {
            clearSession();
            if (
              typeof window !== "undefined" &&
              window.location.pathname !== "/login"
            ) {
              window.location.replace("/login");
            }
            throw new Error("Your session expired. Please sign in again.");
          }

          const fallback =
            response.status >= 500
              ? "Server is currently busy. Please try again shortly."
              : "Request failed";
          const error = new Error(extractErrorMessage(payload, fallback));
          error.status = response.status;
          throw error;
        }

        if (response.status === 204) {
          return null;
        }
        const payload = await response.json().catch(() => null);
        if (cacheEnabled && dedupeKey) {
          getResponseCache.set(dedupeKey, {
            value: payload,
            expiresAt: Date.now() + cacheTtlMs,
          });
        }
        return payload;
      } catch (error) {
        const isAbort = error?.name === "AbortError";
        const isNetwork = error instanceof TypeError;
        const canRetry = attempt < retryCount && (isAbort || isNetwork);

        if (canRetry) {
          await new Promise((resolve) =>
            setTimeout(resolve, 550 * (attempt + 1)),
          );
          continue;
        }

        if (isAbort) {
          throw new Error(
            "Server took too long to respond. Please retry in a few seconds.",
          );
        }
        if (isNetwork) {
          throw new Error(
            "Cannot connect to server. Ensure backend is running on localhost:8000.",
          );
        }
        throw error;
      } finally {
        clearTimeout(timeoutId);
      }
    }

    throw new Error("Request failed. Please try again.");
  };

  if (!dedupeKey) {
    return run();
  }

  const promise = run().finally(() => {
    inflightGetRequests.delete(dedupeKey);
  });
  inflightGetRequests.set(dedupeKey, promise);
  return promise;
}

export function register(name, email, password) {
  return request("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email, password }),
  });
}

export async function login(email, password) {
  const payload = await request("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  setToken(payload.access_token);
  return payload;
}

export function changePassword(currentPassword, newPassword) {
  return request("/api/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export function listDocuments(options = {}) {
  const params = new URLSearchParams();
  if (typeof options.withOverview === "boolean") {
    params.set("with_overview", String(options.withOverview));
  }
  const query = params.toString();
  return request(`/api/documents${query ? `?${query}` : ""}`, {
    cacheTtlMs: options.cacheTtlMs ?? 3000,
  });
}

export function getDocumentsCount() {
  return request("/api/documents/count", { cacheTtlMs: 3000 });
}

export function uploadDocument(file) {
  const formData = new FormData();
  formData.append("file", file);
  return request("/api/documents/upload", {
    method: "POST",
    body: formData,
  }).then((payload) => {
    invalidateGetCache(["/api/documents"]);
    return payload;
  });
}

export function startPractice(documentId, options = {}) {
  const payload = { document_id: documentId };
  if (options.analysisRecordId) {
    payload.analysis_record_id = options.analysisRecordId;
  }
  if (options.inputType === "jd" || options.inputType === "resume") {
    payload.input_type = options.inputType;
  }
  if (options.resumeText) {
    payload.resume_text = options.resumeText;
  }
  return request("/api/practice/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getQuestion(sessionId) {
  return request(`/api/practice/${sessionId}/question`);
}

export function submitAnswer(sessionId, questionId, answer) {
  return request("/api/practice/answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      question_id: questionId,
      answer,
    }),
  });
}

export function analyzeResumeMatch(jdFile, resumeFile, practiceAnswers = []) {
  const formData = new FormData();
  formData.append("jd_file", jdFile);
  formData.append("resume_file", resumeFile);
  if (Array.isArray(practiceAnswers) && practiceAnswers.length) {
    formData.append("practice_answers", JSON.stringify(practiceAnswers));
  }
  return request("/api/analysis/match", {
    method: "POST",
    body: formData,
    timeoutMs: 120000,
  });
}

export function startHrPractice(analysisRecordId) {
  return request("/api/analysis/hr-practice/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysis_record_id: analysisRecordId }),
    timeoutMs: 60000,
  });
}

export function evaluateHrPractice(analysisRecordId, answers) {
  return request("/api/analysis/hr-practice/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysis_record_id: analysisRecordId, answers }),
    timeoutMs: 90000,
  });
}

export function generateResumeUpgrade(analysisRecordId, customPrompt = "") {
  return request("/api/analysis/resume-upgrade/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      analysis_record_id: analysisRecordId,
      custom_prompt: customPrompt,
    }),
    timeoutMs: 45000,
  });
}

export function startSkillUpdate(analysisRecordId) {
  return request("/api/analysis/skill-update/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysis_record_id: analysisRecordId }),
    timeoutMs: 45000,
  });
}

export function generateSkillRoadmap(analysisRecordId, target) {
  const payload = { target };
  if (analysisRecordId) {
    payload.analysis_record_id = analysisRecordId;
  }
  return request("/api/analysis/skill-update/roadmap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    timeoutMs: 120000,
    retry: true,
    retryCount: 1,
  });
}

export function startSkillStepAssessment({
  analysisRecordId,
  target,
  stepTitle,
  stepDescription,
  actionItems = [],
  questionCount = 8,
}) {
  const payload = {
    target,
    step_title: stepTitle,
    step_description: stepDescription || "",
    action_items: Array.isArray(actionItems) ? actionItems : [],
    question_count: questionCount,
  };

  if (analysisRecordId) {
    payload.analysis_record_id = analysisRecordId;
  }

  return request("/api/analysis/skill-update/step-assessment/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    timeoutMs: 90000,
  });
}

export function evaluateSkillStepAssessment(sessionId, answers) {
  return request("/api/analysis/skill-update/step-assessment/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, answers }),
    timeoutMs: 90000,
  });
}

export function startMcqAssessment(analysisRecordId, questionCount = 10) {
  return request("/api/analysis/mcq-assessment/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      analysis_record_id: analysisRecordId,
      question_count: questionCount,
    }),
    timeoutMs: 90000,
  });
}

export function evaluateMcqAssessment(analysisRecordId, answers) {
  return request("/api/analysis/mcq-assessment/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysis_record_id: analysisRecordId, answers }),
    timeoutMs: 90000,
  });
}

export function startResumeAssessment(analysisRecordId, questionCount = 10) {
  return request("/api/analysis/resume-assessment/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      analysis_record_id: analysisRecordId,
      question_count: questionCount,
    }),
    timeoutMs: 90000,
  });
}

export function evaluateResumeAssessment(analysisRecordId, answers) {
  return request("/api/analysis/resume-assessment/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysis_record_id: analysisRecordId, answers }),
    timeoutMs: 90000,
  });
}
