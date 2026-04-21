import { useEffect, useState } from "react";
import {
  FiArrowLeft,
  FiCheck,
  FiClipboard,
  FiLoader,
  FiRefreshCw,
  FiZap,
} from "react-icons/fi";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { generateResumeUpgrade } from "../api";
import AppShell from "../components/layout/AppShell";
import { notifyError } from "../utils/toast";

const ANALYSIS_BACK_CACHE_KEY = "jarvis_analysis_back_cache";
const RESUME_UPGRADE_INTENT_KEY = "jarvis_resume_upgrade_intent";
const REWRITE_RULES = [
  "Use proper sections (Summary, Experience, Projects, Skills, Education)",
  "Use bullet points",
  "Start each bullet with strong action verbs (Built, Developed, Designed)",
  "Avoid repetition",
  "Keep it concise and realistic",
  "Do NOT use words like \"Delivered\"",
  "Maintain professional tone",
];

const ATS_IMPROVEMENT_POINTS = [
  "Polishes your resume language to sound more professional and recruiter-ready.",
  "Keeps your original experience and project data while improving clarity.",
  "Reorganizes content into ATS-friendly sections for better readability.",
  "Strengthens bullet points with clear action-oriented phrasing.",
  "Improves keyword alignment for better role matching in ATS scans.",
];

const DEFAULT_UPGRADE_PROMPT = `Rewrite this resume into a professional ATS-friendly format.

Rules:
${REWRITE_RULES.map((rule) => `- ${rule}`).join("\n")}

Template:
{
  "summary": "",
  "experience": [],
  "projects": [],
  "skills": [],
  "education": []
}`;

const ATS_SECTION_HEADINGS = [
  "PROFESSIONAL SUMMARY",
  "WORK EXPERIENCE",
  "PROJECTS",
  "EDUCATION",
  "SKILLS",
  "POSITIONS OF RESPONSIBILITY",
  "CERTIFICATIONS",
  "SUGGESTED SKILLS TO ADD",
];

const ENTRY_GROUP_SECTIONS = new Set([
  "WORK EXPERIENCE",
  "PROJECTS",
  "POSITIONS OF RESPONSIBILITY",
]);

function isSectionHeading(line) {
  return ATS_SECTION_HEADINGS.includes(String(line || "").toUpperCase());
}

function isMetaLine(text) {
  const line = String(text || "").trim();
  if (!line) return false;
  return /\b\d{2}\/\d{4}\s*[–-]\s*(?:\d{2}\/\d{4}|present)\b|^📍|^🗓|\|/i.test(line);
}

function isEntryHeading(sectionTitle, text) {
  const line = String(text || "").trim();
  if (!line) return false;
  if (!ENTRY_GROUP_SECTIONS.has(String(sectionTitle || "").toUpperCase())) return false;
  if (isMetaLine(line)) return false;
  if (/^[\-•*]\s+/.test(line)) return false;
  if (/[.!?]$/.test(line)) return false;
  return line.length <= 140;
}

function parseAtsResume(rawText) {
  const text = String(rawText || "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");

  const lines = text.split("\n").map((line) => line.trim());
  const hasNonEmpty = lines.some((line) => line.length > 0);

  if (!hasNonEmpty) {
    return {
      header: { name: "", role: "", contact: "" },
      sections: [],
    };
  }

  let cursor = 0;
  while (cursor < lines.length && !lines[cursor]) cursor += 1;

  const header = { name: "", role: "", contact: "" };
  const contactLines = [];

  const firstLine = lines[cursor] || "";
  const isHeading = isSectionHeading(firstLine);
  if (!isHeading) {
    header.name = firstLine;
    cursor = Math.max(cursor, 1);
  }

  while (cursor < lines.length) {
    const line = lines[cursor];
    if (!line) {
      cursor += 1;
      continue;
    }
    if (isSectionHeading(line)) break;

    const looksLikeContact = /@|\+\d|linkedin|github|portfolio|\.com/i.test(line);
    if (looksLikeContact) {
      contactLines.push(line);
    } else if (!header.role) {
      header.role = line;
    } else {
      contactLines.push(line);
    }

    cursor += 1;
  }
  header.contact = contactLines.join("\n");

  const sections = [];
  let current = null;

  for (let i = cursor; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line) {
      if (current && current.items.length) {
        const last = current.items[current.items.length - 1];
        if (last?.type !== "break") {
          current.items.push({ type: "break", text: "" });
        }
      }
      continue;
    }

    const upper = line.toUpperCase();

    if (isSectionHeading(upper)) {
      if (current) sections.push(current);
      current = { title: upper, items: [] };
      continue;
    }

    if (!current) {
      current = { title: "DETAILS", items: [] };
    }

    if (/^[\-•*]\s+/.test(line)) {
      current.items.push({
        type: "bullet",
        text: line.replace(/^[\-•*]\s+/, "").trim(),
      });
      continue;
    }

    current.items.push({ type: "line", text: line });
  }

  if (current) sections.push(current);

  const normalizedSections = sections.map((section) => {
    const items = [...section.items];
    while (items.length && items[items.length - 1]?.type === "break") {
      items.pop();
    }
    return { ...section, items };
  });

  return { header, sections: normalizedSections };
}

export default function AnalysisResumeUpgradePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();

  const stateRecordId = String(location.state?.analysisRecordId || "").trim();
  const queryRecordId = String(searchParams.get("record") || "").trim();
  const cachedRecordId = (() => {
    try {
      const raw = sessionStorage.getItem(ANALYSIS_BACK_CACHE_KEY);
      if (!raw) return "";
      const parsed = JSON.parse(raw);
      const candidate =
        parsed?.analysis?.analysis_record_id ||
        parsed?.analysis?.analysisRecordId ||
        parsed?.analysis?.record_id ||
        parsed?.analysis?._id ||
        "";
      return String(candidate || "").trim();
    } catch {
      return "";
    }
  })();
  const analysisRecordId = stateRecordId || queryRecordId || cachedRecordId;

  const [customPrompt, setCustomPrompt] = useState(DEFAULT_UPGRADE_PROMPT);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const parsedResume = parseAtsResume(result?.ats_resume || "");

  useEffect(() => {
    if (error) {
      notifyError(error);
    }
  }, [error]);

  useEffect(() => {
    sessionStorage.removeItem(RESUME_UPGRADE_INTENT_KEY);
  }, []);

  useEffect(() => {
    if (!analysisRecordId || result || generating) return;

    handleGenerate(DEFAULT_UPGRADE_PROMPT);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisRecordId]);

  async function handleGenerate(promptText = customPrompt) {
    if (!analysisRecordId || generating) return;

    setGenerating(true);
    setError("");
    setCopied(false);

    try {
      const payload = await generateResumeUpgrade(
        analysisRecordId,
        String(promptText || "").trim(),
      );
      setResult(payload);
    } catch (err) {
      setError(err.message || "Could not generate ATS resume rewrite.");
    } finally {
      setGenerating(false);
    }
  }

  async function copyGeneratedResume() {
    if (!result?.ats_resume) return;

    try {
      await navigator.clipboard.writeText(result.ats_resume);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Copy failed. Please select and copy manually.");
    }
  }

  return (
    <AppShell
      title="UpSkill Your Resume"
      subtitle="Generate an ATS-friendly rewrite from your uploaded resume and JD analysis."
      fullBleed
      darkShell
    >
      <div className="relative h-full min-h-0 space-y-5 overflow-x-hidden overflow-y-auto pb-8 pr-1">
        <div className="pointer-events-none absolute -left-20 top-24 h-72 w-72 rounded-full bg-indigo-500/10 blur-[90px]" />
        <div className="pointer-events-none absolute -right-10 bottom-2 h-72 w-72 rounded-full bg-violet-500/10 blur-[100px]" />

        <div className="relative flex justify-between gap-3">
          <button
            type="button"
            onClick={() => navigate("/analysis", { state: { preserveAnalysis: true } })}
            className="inline-flex items-center gap-2 rounded-full border border-slate-700 bg-slate-900/80 px-4 py-2 text-sm font-medium text-slate-100 transition hover:border-slate-500"
          >
            <FiArrowLeft className="text-sm" />
            Back To Analysis
          </button>

          {analysisRecordId && (
            <span className="inline-flex items-center gap-2 rounded-full border border-indigo-500/40 bg-indigo-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-indigo-200">
              <FiZap className="text-xs" />
              ATS Resume Rewriter
            </span>
          )}
        </div>

        {!analysisRecordId && (
          <section className="rounded-2xl border border-amber-400/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            Open this page from the analysis result to use your uploaded JD and resume.
          </section>
        )}

        {analysisRecordId && (
          <section className="grid gap-5 xl:grid-cols-[420px_1fr]">
            <article className="rounded-[26px] border border-slate-800 bg-[#0c132d] p-5 shadow-[0_18px_36px_rgba(2,8,24,0.35)]">
              <h2 className="text-2xl font-semibold tracking-tight text-slate-100">
                Rewrite Instructions
              </h2>
              <p className="mt-2 text-sm text-slate-400">
                Tune your prompt before generating. The rewrite uses your existing analysis context.
              </p>

              <div className="mt-4 rounded-xl border border-slate-800 bg-[#0a1128] px-4 py-3">
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-indigo-300">
                  ATS Resume Benefits
                </p>
                <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-6 text-slate-300">
                  {ATS_IMPROVEMENT_POINTS.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
              </div>

              <button
                type="button"
                disabled={generating}
                onClick={() => handleGenerate(customPrompt)}
                className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-[linear-gradient(90deg,#7c8cff,#9c7cf8)] px-5 py-3 text-sm font-semibold text-slate-900 shadow-[0_18px_36px_rgba(99,102,241,0.35)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-55"
              >
                {generating ? <FiLoader className="animate-spin text-sm" /> : <FiRefreshCw className="text-sm" />}
                {generating ? "Generating ATS Resume..." : "Generate ATS Rewrite"}
              </button>
            </article>

            <article className="rounded-[26px] border border-slate-800 bg-[#0b122b] p-5 shadow-[0_18px_36px_rgba(2,8,24,0.35)]">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-2xl font-semibold tracking-tight text-slate-100">
                    Generated ATS Resume
                  </h2>
                  <p className="mt-1 text-sm text-slate-400">
                    Professional, keyword-aligned version for your target role.
                  </p>
                </div>

                <button
                  type="button"
                  disabled={!result?.ats_resume}
                  onClick={copyGeneratedResume}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs font-semibold uppercase tracking-[0.1em] text-slate-200 transition hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {copied ? <FiCheck className="text-sm text-emerald-300" /> : <FiClipboard className="text-sm" />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>

              {result ? (
                <>
                  

                  {error && (
                    <section className="mt-4 rounded-2xl border border-rose-400/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                      {error}
                    </section>
                  )}

                  <div className="mt-4 max-h-[540px] overflow-auto rounded-2xl border border-slate-800 bg-[#080f24] p-5">
                    {parsedResume.header.name ? (
                      <header className="border-b border-slate-800 pb-4">
                        <h3 className="text-3xl font-bold uppercase tracking-[0.04em] text-slate-100">
                          {parsedResume.header.name}
                        </h3>
                        {parsedResume.header.role && (
                          <p className="mt-2 text-sm font-semibold text-slate-300">
                            {parsedResume.header.role}
                          </p>
                        )}
                        {parsedResume.header.contact && (
                          <p className="mt-1 whitespace-pre-line text-xs text-slate-400">{parsedResume.header.contact}</p>
                        )}
                      </header>
                    ) : null}

                    <div className="mt-4 space-y-5">
                      {parsedResume.sections.map((section) => (
                        <section key={section.title}>
                          <h4 className="border-b border-slate-800 pb-1 text-lg font-semibold uppercase tracking-[0.06em] text-slate-100">
                            {section.title}
                          </h4>
                          <div className="mt-2">
                            {section.items.map((item, index) => {
                              if (item.type === "break") {
                                return <div key={`${section.title}-break-${index}`} className="h-2" />;
                              }

                              if (item.type === "bullet") {
                                return (
                                  <div
                                    key={`${section.title}-bullet-${index}`}
                                    className="mt-1.5 flex gap-2 text-sm leading-6 text-slate-300"
                                  >
                                    <span className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-indigo-300" />
                                    <span>{item.text}</span>
                                  </div>
                                );
                              }

                              const headingLike = isEntryHeading(section.title, item.text);
                              const metaLike = isMetaLine(item.text);
                              const lineClass = headingLike
                                ? "mt-2 text-base font-semibold text-slate-100"
                                : metaLike
                                  ? "mt-1 text-xs text-slate-400"
                                  : "mt-2 text-sm leading-6 text-slate-300";

                              return (
                                <p
                                  key={`${section.title}-line-${index}`}
                                  className={lineClass}
                                >
                                  {item.text}
                                </p>
                              );
                            })}
                          </div>
                        </section>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <div className="mt-6 flex min-h-[320px] items-center justify-center rounded-2xl border border-slate-800 bg-[#080f24] text-sm text-slate-400">
                  {generating ? "Building ATS rewrite from your resume and JD..." : "Click Generate ATS Rewrite to start."}
                </div>
              )}
            </article>
          </section>
        )}
      </div>
    </AppShell>
  );
}
