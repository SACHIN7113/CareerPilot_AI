import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FiBriefcase, FiClock, FiFileText, FiTarget, FiUploadCloud, FiZap } from "react-icons/fi";

import AppShell from "../components/layout/AppShell";
import { listDocuments, uploadDocument } from "../api";
import { notifyError, notifySuccess } from "../utils/toast";
import {
  patchPracticeStats,
  pushDocumentUploadHistory,
  readDocumentUploadHistory,
  writeDocumentUploadHistory,
} from "../utils/storage";

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString();
}

export default function DocumentsPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const uploadProgressTimerRef = useRef(null);
  const uploadProgressResetRef = useRef(null);
  const didLoadDocumentsRef = useRef(false);

  const [documents, setDocuments] = useState([]);
  const [selectedDocument, setSelectedDocument] = useState("");
  const [uploadHistory, setUploadHistory] = useState(readDocumentUploadHistory());
  const [activeTab, setActiveTab] = useState("document");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploadingFileName, setUploadingFileName] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);

  useEffect(() => {
    if (didLoadDocumentsRef.current) return;
    didLoadDocumentsRef.current = true;
    refreshDocuments({ withOverview: true });
  }, []);

  useEffect(() => {
    if (activeTab !== "history") return;
    refreshDocuments({ withOverview: false });
  }, [activeTab]);

  useEffect(() => {
    if (error) {
      notifyError(error);
    }
  }, [error]);

  useEffect(() => {
    return () => {
      if (uploadProgressTimerRef.current) {
        clearInterval(uploadProgressTimerRef.current);
      }
      if (uploadProgressResetRef.current) {
        clearTimeout(uploadProgressResetRef.current);
      }
    };
  }, []);

  function startUploadProgress(fileName) {
    if (uploadProgressTimerRef.current) {
      clearInterval(uploadProgressTimerRef.current);
    }
    if (uploadProgressResetRef.current) {
      clearTimeout(uploadProgressResetRef.current);
    }

    setUploadingFileName(fileName || "Document");
    setUploadProgress(7);

    uploadProgressTimerRef.current = setInterval(() => {
      setUploadProgress((prev) => {
        if (prev >= 88) return prev;
        const step = Math.max(1, Math.ceil((88 - prev) / 7));
        return Math.min(88, prev + step);
      });
    }, 320);
  }

  function finishUploadProgress() {
    if (uploadProgressTimerRef.current) {
      clearInterval(uploadProgressTimerRef.current);
      uploadProgressTimerRef.current = null;
    }
    setUploadProgress(100);

    uploadProgressResetRef.current = setTimeout(() => {
      setUploadProgress(0);
      setUploadingFileName("");
      uploadProgressResetRef.current = null;
    }, 900);
  }

  async function refreshDocuments(options = {}) {
    try {
      const withOverview =
        typeof options.withOverview === "boolean" ? options.withOverview : true;
      const payload = await listDocuments({ withOverview });

      setDocuments((prev) => {
        if (!Array.isArray(payload)) return [];
        const previousMap = new Map((prev || []).map((item) => [item.id, item]));
        return payload.map((item) => {
          if (item?.jd_overview) return item;
          const cached = previousMap.get(item?.id);
          return cached?.jd_overview ? { ...item, jd_overview: cached.jd_overview } : item;
        });
      });

      const localHistory = readDocumentUploadHistory();
      const localMap = new Map(localHistory.map((item) => [item.id, item]));
      const dbRows = payload.map((doc) => ({
        id: doc.id,
        title: doc.title || "untitled",
        uploadedAt: localMap.get(doc.id)?.uploadedAt || doc.created_at || new Date().toISOString(),
        source: localMap.get(doc.id)?.source || "db",
      }));
      const dbIds = new Set(payload.map((doc) => doc.id));
      const localOnly = localHistory.filter((item) => item?.id && !dbIds.has(item.id));
      const mergedHistory = [...dbRows, ...localOnly]
        .sort((a, b) => new Date(b.uploadedAt || 0).getTime() - new Date(a.uploadedAt || 0).getTime())
        .slice(0, 200);

      writeDocumentUploadHistory(mergedHistory);
      setUploadHistory(mergedHistory);

      if (payload.length && selectedDocument) {
        const selectedExists = payload.some((item) => item.id === selectedDocument);
        if (!selectedExists) {
          setSelectedDocument("");
        }
      }
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleUpload(event) {
    if (loading) {
      event.target.value = "";
      return;
    }

    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    setLoading(true);
    setError("");
    startUploadProgress(file.name);
    try {
      const uploaded = await uploadDocument(file);
      const nextHistory = pushDocumentUploadHistory(uploaded, "documents");
      setUploadHistory(nextHistory);
      await refreshDocuments();
      setSelectedDocument(uploaded.id);
      setActiveTab("document");
      notifySuccess("Document uploaded successfully.");

      patchPracticeStats((stats) => ({
        ...stats,
        documentsUploaded: stats.documentsUploaded + 1,
        lastDocumentTitle: uploaded.title || file.name,
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      finishUploadProgress();
      event.target.value = "";
    }
  }

  function selectDocument(docId) {
    setSelectedDocument(docId);
  }

  const activeDocument = documents.find((item) => item.id === selectedDocument) || null;
  const activeOverview = activeDocument?.jd_overview || null;
  const activeSkills = activeOverview?.required_skills || [];
  const activeRequirements = activeOverview?.key_requirements || [];
  const activePrepTips = activeOverview?.what_to_prepare || [];
  const highlightedRequirements = activeRequirements.slice(0, 4);
  const strategyCards = activePrepTips.slice(0, 4);

  const historyRows = useMemo(() => {
    const localMap = new Map(uploadHistory.map((item) => [item.id, item]));

    const fromDb = documents.map((doc) => {
      const local = localMap.get(doc.id);
      return {
        id: doc.id,
        title: doc.title,
        uploadedAt: local?.uploadedAt || doc.created_at || null,
        source: local?.source || "db",
      };
    });

    const dbIds = new Set(documents.map((doc) => doc.id));
    const localOnly = uploadHistory
      .filter((item) => item?.id && !dbIds.has(item.id))
      .map((item) => ({
        id: item.id,
        title: item.title || "untitled",
        uploadedAt: item.uploadedAt || null,
        source: item.source || "local",
      }));

    return [...fromDb, ...localOnly].sort((a, b) => {
      const aTime = new Date(a.uploadedAt || 0).getTime();
      const bTime = new Date(b.uploadedAt || 0).getTime();
      return bTime - aTime;
    });
  }, [documents, uploadHistory]);

  return (
    <AppShell title="Documents" subtitle="Upload documents, track history, and choose the active learning document.">
      <div className="space-y-6">
        <section className="relative overflow-hidden rounded-[28px] border border-slate-800 bg-[#040b1d] p-6 shadow-[0_20px_48px_rgba(2,8,24,0.45)]">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(70%_120%_at_50%_0%,rgba(45,212,191,0.18)_0%,rgba(5,10,26,0)_55%),radial-gradient(45%_60%_at_15%_25%,rgba(59,130,246,0.2)_0%,rgba(59,130,246,0)_70%),radial-gradient(40%_55%_at_85%_20%,rgba(168,85,247,0.16)_0%,rgba(168,85,247,0)_70%)]" />
          <div className="pointer-events-none absolute inset-0 opacity-50 bg-[repeating-linear-gradient(120deg,rgba(56,189,248,0.07)_0px,rgba(56,189,248,0.07)_1px,transparent_1px,transparent_44px)]" />
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,rgba(2,6,23,0.15)_0%,rgba(2,6,23,0.78)_100%)]" />

          <div className="relative flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-3xl">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Document Intelligence</p>
              <h2 className="mt-3 text-4xl font-semibold tracking-tight text-slate-100 md:text-5xl"> JD Document AI Brief</h2>
              <p className="mt-3 text-sm text-slate-300 md:text-lg">
                Upload your target job description. Our AI models dissect role nuances and build a custom high-fidelity preparation strategy.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => navigate("/aiPrepare")}
                className="inline-flex items-center rounded-xl border border-slate-600/70 bg-slate-900/50 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-400"
              >
                Back to AI Prepare
              </button>
            </div>
          </div>

          <div className="relative mt-6 grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-center">
            <div className="flex items-center gap-3 rounded-xl border border-slate-700 bg-[#0d1838] px-4 py-3">
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-600 bg-slate-900/60 text-slate-300">
                <FiFileText className="text-base" />
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-100">
                  {activeDocument?.title || "Drop Job Description (PDF/TXT)"}
                </p>
                <p className="text-xs text-slate-500">{activeDocument ? "Active document selected" : "Select file to begin analysis"}</p>
              </div>
            </div>

            <button
              type="button"
              disabled={loading}
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-300/40 bg-cyan-500/10 px-4 py-3 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:border-cyan-700/40 disabled:bg-cyan-900/20 disabled:text-cyan-400/80"
            >
              <FiUploadCloud className="text-base" />
              {loading ? "Uploading..." : "Upload File"}
            </button>

            <div className="inline-flex rounded-xl border border-slate-700 bg-[#0b1433] p-1">
              <button
                type="button"
                onClick={() => setActiveTab("document")}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                  activeTab === "document"
                    ? "border border-slate-600 bg-[#111d45] text-slate-100 shadow-sm"
                    : "text-slate-400"
                }`}
              >
                Document
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("history")}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                  activeTab === "history"
                    ? "border border-slate-600 bg-[#111d45] text-slate-100 shadow-sm"
                    : "text-slate-400"
                }`}
              >
                <FiClock className="text-sm" />
                History
              </button>
            </div>
          </div>


          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.pdf,.docx"
            onChange={handleUpload}
            className="hidden"
          />

        </section>

        {activeTab === "document" && (
          <section className="space-y-5">
            {loading || uploadProgress > 0 ? (
              <div className="rounded-[28px] border border-[rgba(167,165,255,0.22)] bg-[linear-gradient(112deg,#201f1f_0%,#26242d_100%)] p-5 shadow-[0_20px_48px_rgba(2,8,24,0.45)]">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-3xl font-semibold tracking-tight text-slate-100">{uploadingFileName || "Document"}</p>
                    <p className="mt-1 text-base text-[#a7a5ff]">Uploading & Analyzing...</p>
                  </div>
                  <div className="rounded-full bg-[rgba(38,38,38,0.8)] px-3 py-1.5 text-xs font-semibold text-slate-300">
                    Processing {Math.max(1, uploadProgress)}%
                  </div>
                </div>

                <p className="mt-6 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Neural Mapping Progress</p>
                <div className="mt-2 h-2 rounded-full bg-black/70">
                  <div
                    className="h-full rounded-full bg-[linear-gradient(90deg,#a7a5ff_0%,#645efb_100%)] transition-[width] duration-300"
                    style={{ width: `${Math.max(1, Math.min(100, uploadProgress))}%` }}
                  />
                </div>
              </div>
            ) : activeDocument ? (
              <div className="rounded-[28px] border border-slate-800 bg-[#09132f] p-5 shadow-[0_20px_48px_rgba(2,8,24,0.45)]">
                <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr_1fr]">
                  <article className="rounded-2xl border border-slate-700 bg-slate-900/45 p-4">
                    <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-cyan-300">
                      <FiBriefcase className="text-sm" />
                      Target Organization
                    </div>
                    <h3 className="mt-2 text-3xl font-semibold tracking-tight text-slate-100">{activeOverview?.company_name || "Selected Organization"}</h3>
                    <p className="mt-2 text-sm leading-7 text-slate-300">
                      {activeOverview?.overview || "Upload or choose a document to generate organization context and role positioning."}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      
                    </div>
                  </article>

                  <article className="rounded-2xl border border-slate-700 bg-slate-900/45 p-4">
                    <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-violet-300">
                      <FiTarget className="text-sm" />
                      Role Snapshot
                    </div>
                    <p className="mt-3 text-xs uppercase tracking-[0.14em] text-slate-500">Role Title</p>
                    <p className="mt-1 text-2xl font-semibold text-slate-100">{activeOverview?.role_title || "Target Role"}</p>
                    <p className="mt-4 text-xs uppercase tracking-[0.14em] text-slate-500">Match Inputs</p>
                    <p className="mt-1 text-sm text-slate-200">Requirements: {activeRequirements.length || 0}</p>
                    <p className="mt-1 text-sm text-slate-200">Skills Tagged: {activeSkills.length || 0}</p>
                  </article>

                  <article className="rounded-2xl border border-slate-700 bg-slate-900/45 p-4">
                    <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-emerald-300">
                      <FiFileText className="text-sm" />
                      Skill Taxonomy
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {activeSkills.length ? (
                        activeSkills.map((skill) => (
                          <span key={skill} className="rounded-md border border-slate-600 bg-slate-800/70 px-2 py-1 text-xs text-slate-200">
                            {skill}
                          </span>
                        ))
                      ) : (
                        <p className="text-sm text-slate-400">No skills extracted yet.</p>
                      )}
                    </div>
                  </article>
                </div>
              </div>
            ) : (
              <div className="rounded-[28px] border border-slate-800 bg-[#09132f] p-8 text-center shadow-[0_20px_48px_rgba(2,8,24,0.45)]">
                <p className="text-lg font-medium text-slate-200">Upload a document to activate intelligence view.</p>
                <p className="mt-2 text-sm text-slate-400">The organization profile, role snapshot, and strategy panels will appear here.</p>
              </div>
            )}

            {activeDocument && !loading && uploadProgress === 0 && (
              <div className="grid gap-5 xl:grid-cols-[1.1fr_1.45fr]">
                <section className="rounded-[26px] border border-slate-800 bg-[#09132f] p-5 shadow-[0_20px_48px_rgba(2,8,24,0.45)]">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-2xl font-semibold tracking-tight text-slate-100">Company Requirements</h3>
                    <p className="text-xs text-slate-400">{highlightedRequirements.length || 0} Key Priority Areas</p>
                  </div>

                  <div className="mt-4 space-y-3">
                    {highlightedRequirements.length ? (
                      highlightedRequirements.map((point) => (
                        <article key={point} className="rounded-xl border border-slate-700 bg-slate-900/40 p-3">
                          <div className="flex items-start gap-2">
                            <span className="mt-1 inline-flex h-2 w-2 rounded-full bg-cyan-300" />
                            <p className="text-sm leading-6 text-slate-200">{point}</p>
                          </div>
                        </article>
                      ))
                    ) : (
                      <p className="text-sm text-slate-400">No requirement points found for this document yet.</p>
                    )}
                  </div>
                </section>

                <section className="rounded-[26px] border border-slate-800 bg-[#09132f] p-5 shadow-[0_20px_48px_rgba(2,8,24,0.45)]">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-indigo-500/40 bg-indigo-500/15 text-indigo-300">
                        <FiZap className="text-lg" />
                      </span>
                      <h3 className="text-3xl font-semibold tracking-tight text-slate-100">AI Preparation Strategy</h3>
                    </div>
                 
                  </div>

                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    {strategyCards.length ? (
                      strategyCards.map((tip) => (
                        <article key={tip} className="rounded-xl border border-slate-700 bg-slate-900/45 p-3">
                          <p className="text-xs uppercase tracking-[0.14em] text-slate-500">Portfolio Focus</p>
                          <p className="mt-2 text-sm leading-6 text-slate-200">{tip}</p>
                        </article>
                      ))
                    ) : (
                      <p className="text-sm text-slate-400">Preparation strategy will appear once AI extracts tips from the document.</p>
                    )}
                  </div>
                </section>
              </div>
            )}
          </section>
        )}

        {activeTab === "history" && (
          <section className="rounded-[28px] border border-slate-800 bg-[#09132f] p-5 shadow-[0_20px_48px_rgba(2,8,24,0.45)]">
            <div className="mb-4 flex items-center justify-between gap-2">
              <h3 className="text-2xl font-semibold tracking-tight text-slate-100">Upload History</h3>
              <p className="text-sm text-slate-400">Select a file to load its brief</p>
            </div>

            <div className="space-y-3">
              {historyRows.length ? (
                historyRows.map((row) => {
                  const isSelected = selectedDocument === row.id;
                  return (
                    <article
                      key={row.id}
                      className={`rounded-2xl border p-4 transition ${
                        isSelected
                          ? "border-indigo-500/60 bg-indigo-500/10"
                          : "border-slate-700 bg-slate-900/35"
                      }`}
                    >
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                        <div className="min-w-0">
                          <p className="truncate text-lg font-semibold text-slate-100">{row.title}</p>
                          <p className="mt-1 text-xs uppercase tracking-[0.14em] text-slate-500">Document ID {row.id}</p>
                          <p className="mt-1 text-sm text-slate-300">Uploaded: {formatDate(row.uploadedAt)}</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            selectDocument(row.id);
                            setActiveTab("document");
                          }}
                          className="inline-flex items-center gap-2 rounded-xl border border-indigo-400/40 bg-indigo-500/10 px-4 py-2 text-sm font-semibold text-indigo-200 transition hover:bg-indigo-500/20"
                        >
                          <FiFileText className="text-sm" />
                          Open document brief
                        </button>
                      </div>
                    </article>
                  );
                })
              ) : (
                <div className="rounded-2xl border border-slate-700 bg-slate-900/40 p-8 text-center text-sm text-slate-300">
                  No upload history available yet.
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </AppShell>
  );
}
