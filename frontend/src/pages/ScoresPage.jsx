import { useEffect, useMemo, useRef, useState } from "react";
import { FiBookOpen, FiClock, FiSearch, FiTrendingUp } from "react-icons/fi";

import AppShell from "../components/layout/AppShell";
import { listDocuments } from "../api";
import { readDocumentUploadHistory, readPracticeStats } from "../utils/storage";
import { notifyError } from "../utils/toast";

function formatDateTime(value) {
  const time = Number(value || 0);
  if (!time) return "Unknown time";
  return new Date(time).toLocaleString();
}

function toMs(value) {
  const time = new Date(value || 0).getTime();
  return Number.isFinite(time) ? time : 0;
}

function trimText(value, max = 150) {
  const text = String(value || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return "-";
  return text.length > max ? `${text.slice(0, max - 1)}...` : text;
}

function buildUploadRows(documents, localHistory) {
  const localMap = new Map(localHistory.map((item) => [item.id, item]));
  const fromDb = documents.map((doc) => ({
    id: doc.id,
    title: doc.title || "Untitled document",
    source: localMap.get(doc.id)?.source || "db",
    uploadedAt: localMap.get(doc.id)?.uploadedAt || doc.created_at || null,
  }));

  const dbIds = new Set(documents.map((doc) => doc.id));
  const localOnly = localHistory
    .filter((item) => item?.id && !dbIds.has(item.id))
    .map((item) => ({
      id: item.id,
      title: item.title || "Untitled document",
      source: item.source || "local",
      uploadedAt: item.uploadedAt || null,
    }));

  const merged = [...fromDb, ...localOnly];
  const deduped = Array.from(
    new Map(merged.map((item) => [item.id, item])).values(),
  );
  return deduped.sort((a, b) => toMs(b.uploadedAt) - toMs(a.uploadedAt));
}

export default function ScoresPage() {
  const didLoadHistoryRef = useRef(false);
  const [stats, setStats] = useState(readPracticeStats());
  const [documents, setDocuments] = useState([]);
  const [uploadHistory, setUploadHistory] = useState(
    readDocumentUploadHistory(),
  );
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (didLoadHistoryRef.current) return;
    didLoadHistoryRef.current = true;
    setStats(readPracticeStats());
    setUploadHistory(readDocumentUploadHistory());
    loadDocuments();
  }, []);

  async function loadDocuments() {
    try {
      const payload = await listDocuments({ withOverview: false });
      setDocuments(Array.isArray(payload) ? payload : []);
    } catch (err) {
      notifyError(err?.message || "Could not load history data.");
      setDocuments([]);
    }
  }

  const uploadRows = useMemo(
    () => buildUploadRows(documents, uploadHistory),
    [documents, uploadHistory],
  );

  const normalizedQuery = query.trim().toLowerCase();

  const filteredUploadRows = useMemo(() => {
    if (!normalizedQuery) return uploadRows;
    return uploadRows.filter((row) => {
      const bag = `${row.title} ${row.source}`.toLowerCase();
      return bag.includes(normalizedQuery);
    });
  }, [uploadRows, normalizedQuery]);

  const latestUploadedTitle =
    uploadRows[0]?.title || "No uploaded document yet";

  const momentum =
    stats.sessionsStarted > 0
      ? Math.min(
          100,
          Math.round((stats.questionsAnswered / stats.sessionsStarted) * 20),
        )
      : 0;

  return (
    <AppShell
      title="History"
      subtitle="Your uploaded document history in one place."
    >
      <div className="space-y-6">
        <section className="relative overflow-hidden rounded-[28px] bg-[linear-gradient(125deg,rgba(10,18,44,0.95)_0%,rgba(19,17,39,0.95)_52%,rgba(8,25,41,0.95)_100%)] p-5 shadow-[0_24px_60px_rgba(2,8,24,0.45)] sm:p-6">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(45%_70%_at_12%_0%,rgba(52,201,255,0.24)_0%,transparent_70%),radial-gradient(42%_60%_at_88%_10%,rgba(143,136,255,0.2)_0%,transparent_70%)]" />

          <div className="relative flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-cyan-300">
                Activity Ledger
              </p>
              <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-100 sm:text-4xl">
                Learning History
              </h2>
              <p className="mt-2 max-w-2xl text-sm text-slate-300 sm:text-base">
                Review all uploaded job descriptions and keep track of your
                latest learning documents.
              </p>
            </div>

            <span className="inline-flex items-center gap-2 rounded-full border border-[rgba(45,212,191,0.35)] bg-[rgba(16,185,129,0.14)] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-emerald-200">
              <FiTrendingUp className="text-sm" />
              Momentum {momentum}%
            </span>
          </div>

          <div className="relative mt-5 grid gap-3 sm:grid-cols-3">
            <article className="rounded-2xl border border-[rgba(148,163,184,0.22)] bg-[rgba(9,14,30,0.68)] p-4">
              <p className="text-xs uppercase tracking-[0.14em] text-slate-400">
                Uploaded Docs
              </p>
              <p className="mt-2 text-2xl font-semibold text-slate-100">
                {uploadRows.length}
              </p>
              <p className="mt-1 text-xs text-slate-400">
                Files in your learning history
              </p>
            </article>

            <article className="rounded-2xl border border-[rgba(148,163,184,0.22)] bg-[rgba(9,14,30,0.68)] p-4">
              <p className="text-xs uppercase tracking-[0.14em] text-slate-400">
                Latest Upload
              </p>
              <p className="mt-2 truncate text-lg font-semibold text-slate-100">
                {trimText(latestUploadedTitle, 45)}
              </p>
              <p className="mt-1 text-xs text-slate-400">
                Most recently uploaded document
              </p>
            </article>

            <article className="rounded-2xl border border-[rgba(148,163,184,0.22)] bg-[rgba(9,14,30,0.68)] p-4">
              <p className="text-xs uppercase tracking-[0.14em] text-slate-400">
                Practice Sessions
              </p>
              <p className="mt-2 text-2xl font-semibold text-slate-100">
                {stats.sessionsStarted}
              </p>
              <p className="mt-1 text-xs text-slate-400">
                Total sessions started
              </p>
            </article>
          </div>
        </section>

        <section className="rounded-3xl  border-t-0 bg-[rgba(18,22,34,0.78)] p-4 backdrop-blur-xl sm:p-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <label className="flex w-full items-center gap-2 rounded-xl border border-[rgba(148,163,184,0.25)] bg-[rgba(8,12,22,0.68)] px-3 py-2 lg:max-w-sm">
              <FiSearch className="text-sm text-slate-500" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search uploaded documents..."
                className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500"
              />
            </label>
          </div>
        </section>

        <section className="rounded-3xl border border-[rgba(148,163,184,0.18)] bg-[rgba(16,18,28,0.82)] p-5 backdrop-blur-xl">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h3 className="inline-flex items-center gap-2 text-lg font-semibold text-slate-100">
              <FiBookOpen className="text-base text-cyan-300" />
              Document Upload History
            </h3>
            <span className="text-xs uppercase tracking-[0.14em] text-slate-500">
              {filteredUploadRows.length} items
            </span>
          </div>

          <div className="space-y-2">
            {filteredUploadRows.length ? (
              filteredUploadRows.map((row) => (
                <article
                  key={row.id}
                  className="flex flex-col gap-2 rounded-2xl border border-[rgba(148,163,184,0.16)] bg-[rgba(8,12,22,0.58)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-100">
                      {row.title}
                    </p>
                    <p className="mt-0.5 text-xs text-slate-400">
                      ID: {row.id}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 text-xs">
                    <span className="inline-flex items-center gap-1 rounded-full border border-[rgba(148,163,184,0.3)] bg-[rgba(15,23,42,0.5)] px-2.5 py-1 text-slate-300">
                      <FiClock className="text-[11px]" />
                      {formatDateTime(toMs(row.uploadedAt))}
                    </span>
                  </div>
                </article>
              ))
            ) : (
              <p className="rounded-2xl border border-dashed border-[rgba(148,163,184,0.3)] bg-[rgba(15,23,42,0.35)] px-4 py-6 text-center text-sm text-slate-400">
                No document uploads found for this filter.
              </p>
            )}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
