const STATS_KEY = "jarvis_practice_stats";
const SELECTED_DOCUMENT_KEY = "jarvis_selected_document";
const DOCUMENT_UPLOAD_HISTORY_KEY = "jarvis_document_upload_history";

const defaultStats = {
  sessionsStarted: 0,
  questionsAnswered: 0,
  documentsUploaded: 0,
  lastDifficulty: 1,
  lastFeedback: "",
  lastDocumentTitle: ""
};

export function readPracticeStats() {
  try {
    const raw = localStorage.getItem(STATS_KEY);
    if (!raw) {
      return { ...defaultStats };
    }
    return { ...defaultStats, ...JSON.parse(raw) };
  } catch {
    return { ...defaultStats };
  }
}

export function writePracticeStats(nextStats) {
  localStorage.setItem(STATS_KEY, JSON.stringify({ ...defaultStats, ...nextStats }));
}

export function patchPracticeStats(patch) {
  const current = readPracticeStats();
  const nextStats = typeof patch === "function" ? patch(current) : { ...current, ...patch };
  writePracticeStats(nextStats);
  return nextStats;
}

export function readSelectedDocument() {
  return localStorage.getItem(SELECTED_DOCUMENT_KEY) || "";
}

export function writeSelectedDocument(documentId) {
  if (documentId) {
    localStorage.setItem(SELECTED_DOCUMENT_KEY, documentId);
  } else {
    localStorage.removeItem(SELECTED_DOCUMENT_KEY);
  }
}

export function readDocumentUploadHistory() {
  try {
    const raw = localStorage.getItem(DOCUMENT_UPLOAD_HISTORY_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function writeDocumentUploadHistory(items) {
  const safeItems = Array.isArray(items) ? items : [];
  localStorage.setItem(DOCUMENT_UPLOAD_HISTORY_KEY, JSON.stringify(safeItems));
}

export function pushDocumentUploadHistory(document, source = "documents") {
  if (!document?.id) {
    return readDocumentUploadHistory();
  }

  const current = readDocumentUploadHistory();
  const nextEntry = {
    id: document.id,
    title: document.title || "untitled",
    uploadedAt: new Date().toISOString(),
    source,
  };

  const deduped = [nextEntry, ...current.filter((item) => item?.id !== document.id)];
  const trimmed = deduped.slice(0, 200);
  writeDocumentUploadHistory(trimmed);
  return trimmed;
}
