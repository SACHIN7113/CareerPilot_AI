import { useEffect, useRef, useState } from "react";
import {
  FiArrowRight,
  FiArrowUp,
  FiCheckCircle,
  FiCpu,
  FiPaperclip,
  FiPlay,
  FiTarget,
  FiZap,
} from "react-icons/fi";
import { useLocation, useNavigate } from "react-router-dom";

import AppShell from "../components/layout/AppShell";
import { analyzeResumeMatch } from "../api";
import { notifyError } from "../utils/toast";

const ANALYSIS_PHASES = [
  "Uploading files to server",
  "Extracting text from JD and resume",
  "Matching role requirements and resume evidence",
  "Generating score, insights, and skill roadmap",
];
const ANALYSIS_BACK_CACHE_KEY = "jarvis_analysis_back_cache";
const RESUME_UPGRADE_INTENT_KEY = "jarvis_resume_upgrade_intent";

function extractAnalysisRecordId(source) {
  if (!source || typeof source !== "object") return "";

  const candidate =
    source.analysis_record_id ||
    source.analysisRecordId ||
    source.record_id ||
    source._id ||
    "";

  return String(candidate || "").trim();
}

function normalizeFilename(value) {
  return String(value || "")
    .replace(/\.[^.]+$/, "")
    .replace(/[_]+/g, " ")
    .trim();
}

function splitFilenameParts(value) {
  return normalizeFilename(value)
    .split(/[-|]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function isValidRoleCandidate(value) {
  const candidate = String(value || "").trim();
  if (!candidate) return false;

  const lowered = candidate.toLowerCase();
  if (
    [
      "this",
      "that",
      "this role",
      "role inferred from uploaded jd",
      "role",
      "unknown",
    ].includes(lowered)
  )
    return false;
  if (/^is\s+/i.test(candidate)) return false;
  if (
    /\b(ctc|lpa|salary|per annum|per year|if you think|job description|fresher|freshers|enthusiastic|curious|batch|students?)\b/i.test(
      candidate,
    )
  )
    return false;

  const hasRoleHint =
    /\b(engineer|developer|analyst|intern|manager|support|specialist|tester|architect|executive|consultant|administrator|trainee|coordinator|sde|qa|lead|director|owner)\b/i.test(
      candidate,
    );
  const hasLevelHint = /\b(l\d+|level\s*\d+)\b/i.test(candidate);
  if (!hasRoleHint && !hasLevelHint) return false;

  if (
    /\b(match|ideal|fit)\b/i.test(candidate) &&
    !/\b(engineer|developer|analyst|intern|manager|support|specialist|tester|architect|executive)\b/i.test(
      candidate,
    )
  ) {
    return false;
  }

  return true;
}

function isValidCompanyCandidate(value) {
  const candidate = String(value || "").trim();
  if (!candidate) return false;

  const lowered = candidate.toLowerCase();
  if (["the company", "our team", "company", "unknown"].includes(lowered))
    return false;
  if (
    /\b(if you think|join our team|ctc|lpa|salary|apply now|job description)\b/i.test(
      candidate,
    )
  )
    return false;
  if (candidate.split(/\s+/).length > 6) return false;

  return true;
}

function deriveCompanyName(analysis, jdFile) {
  const direct = [
    analysis?.company_name,
    analysis?.target_company,
    analysis?.company,
  ]
    .map((item) => String(item || "").trim())
    .find((item) => isValidCompanyCandidate(item));

  if (direct) return direct;

  const parts = splitFilenameParts(analysis?.jd_filename || jdFile?.name || "");
  if (parts.length >= 2 && isValidCompanyCandidate(parts[0])) return parts[0];

  return "Selected Job Description";
}

function inferRoleFromSummary(summary) {
  const text = String(summary || "");
  if (!text) return "";

  const match = text.match(
    /\bfor\s+(?:the\s+)?([A-Za-z0-9/&()\- ]{3,80})\s+role\b/i,
  );
  if (!match) return "";

  const candidate = String(match[1] || "").trim();
  return isValidRoleCandidate(candidate) ? candidate : "";
}

function deriveRoleName(analysis, jdFile) {
  const summaryRole = inferRoleFromSummary(analysis?.summary);
  const direct = [
    summaryRole,
    analysis?.role_title,
    analysis?.target_role,
    analysis?.role,
  ]
    .map((item) => String(item || "").trim())
    .find((item) => isValidRoleCandidate(item));

  if (direct) return direct;

  const parts = splitFilenameParts(analysis?.jd_filename || jdFile?.name || "");
  if (parts.length >= 2) {
    const fromFilename = parts.slice(1).join(" - ");
    if (isValidRoleCandidate(fromFilename)) return fromFilename;
  }
  if (parts.length === 1 && isValidRoleCandidate(parts[0])) return parts[0];

  return "Role inferred from uploaded JD";
}

function getSeverityByIndex(index, total) {
  const highCount = Math.max(1, Math.ceil(total / 2));
  return index < highCount ? "HIGH" : "MEDIUM";
}

function buildSkillNote(skill, analysis) {
  const reasons = analysis?.low_match_reasons || [];
  const found = reasons.find((reason) =>
    reason.toLowerCase().includes(String(skill).toLowerCase()),
  );
  return found || `Resume has limited direct evidence for ${skill}.`;
}

function buildDisplaySummary(analysis, matchScore) {
  const raw = String(analysis?.summary || "").trim();
  const verdict = String(analysis?.verdict || "").toLowerCase();
  const lowReason =
    analysis?.low_match_reasons?.[0] ||
    "Important required JD skills are still missing.";

  if (matchScore < 45 || verdict.includes("low")) {
    return `Current match is ${matchScore}%. You are a developing fit for this role. Main gap: ${lowReason}`;
  }

  return raw || `Resume to JD match is ${matchScore}%.`;
}

function shouldMergeStrengthFragment(fragment) {
  return /^(and|or|with|which|that|while|where|also|including|using)\b/i.test(
    String(fragment || "").trim(),
  );
}

function shouldAttachToPreviousPoint(fragment, previousPoint) {
  const next = String(fragment || "").trim();
  const prev = String(previousPoint || "").trim();
  if (!next || !prev) return false;

  // Attach tails when the previous fragment ends with a dangling preposition.
  if (/\b(at|in|for|with|on|to|from|as)\.?$/i.test(prev)) return true;

  const normalizedNext = next.replace(/[.!?]+$/, "").trim();
  const words = normalizedNext.split(/\s+/).filter(Boolean);
  const hasVerb =
    /\b(is|are|was|were|am|be|been|being|work|works|working|worked|led|built|developed|managed|created|designed|have|has|had|do|does|did|can|will)\b/i.test(
      normalizedNext,
    );

  // Attach short company-style tails like "47billion".
  return words.length > 0 && words.length <= 3 && !hasVerb;
}

function buildStrengthPoints(items) {
  const points = [];

  (Array.isArray(items) ? items : []).forEach((item) => {
    const normalized = String(item || "")
      .replace(/\s+/g, " ")
      .trim();
    if (!normalized) return;

    const fragments = normalized
      .split(/(?<=[.!?])\s+|\s*;\s*|\n+/)
      .map((part) => part.trim())
      .filter(Boolean);

    const source = fragments.length ? fragments : [normalized];
    source.forEach((fragment) => {
      if (points.length && shouldMergeStrengthFragment(fragment)) {
        points[points.length - 1] = `${points[points.length - 1]} ${fragment}`
          .replace(/\s+/g, " ")
          .trim();
        return;
      }
      if (
        points.length &&
        shouldAttachToPreviousPoint(fragment, points[points.length - 1])
      ) {
        points[points.length - 1] = `${points[points.length - 1]} ${fragment}`
          .replace(/\s+/g, " ")
          .trim();
        return;
      }
      points.push(fragment);
    });
  });

  const seen = new Set();
  const cleaned = [];
  for (const point of points) {
    let text = String(point || "")
      .replace(/^[•\-]\s*/, "")
      .replace(/\s+/g, " ")
      .trim();
    if (!text) continue;
    if (!/[.!?]$/.test(text)) text = `${text}.`;

    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    cleaned.push(text);
    if (cleaned.length >= 5) break;
  }

  return cleaned;
}

function UploadFileCard({
  title,
  subtitle,
  fileLabel,
  file,
  onUploadClick,
  helper,
}) {
  return (
    <article className="mx-auto flex h-[340px] w-full max-w-[300px] flex-col rounded-3xl border border-slate-800 bg-[#0c1432] p-4 shadow-[0_24px_44px_rgba(2,8,24,0.45)]">
      <div className="mb-3 flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-indigo-400/40 bg-indigo-500/10 text-indigo-300">
          <FiPaperclip className="text-sm" />
        </span>
        <div className="min-w-0">
          <h2 className="whitespace-nowrap text-[1.75rem] font-semibold leading-none tracking-tight text-slate-100">
            {title}
          </h2>
          <p className="ui-page-kicker mt-1">{subtitle}</p>
        </div>
      </div>

      <div className="min-h-[145px] rounded-2xl border border-slate-800/90 bg-[#0a1028] p-3.5">
        <p className="ui-page-kicker">{fileLabel}</p>
        <p className="mt-2 min-h-[24px] text-sm text-slate-200">
          {file ? file.name : "No file selected"}
        </p>
        <p className="mt-1.5 text-xs leading-5 text-slate-500">{helper}</p>
      </div>

      <button
        type="button"
        onClick={onUploadClick}
        className="mt-4 ui-btn-secondary w-full border-slate-700 bg-slate-900 text-slate-200 hover:bg-slate-800"
      >
        <FiPaperclip className="text-sm" />
        Upload
      </button>
    </article>
  );
}

function LoadingScreen({ phaseIndex, elapsedSeconds }) {
  return (
    <section className="flex min-h-[calc(100vh-220px)] items-center justify-center rounded-3xl border border-slate-800 bg-[#060c22] px-6 py-10">
      <div className="text-center">
        <div className="mx-auto flex h-28 w-28 items-center justify-center rounded-full border border-indigo-500/50 bg-indigo-500/10">
          <span className="relative flex h-16 w-16 items-center justify-center rounded-full border border-indigo-500/50 bg-[#0a1437] text-indigo-300">
            <span className="absolute inset-0 animate-ping rounded-full border border-indigo-400/40" />
            <FiCpu className="relative z-10 text-2xl" />
          </span>
        </div>

        <h2 className="ui-page-title mt-8">Building Your Ecosystem</h2>
        <p className="ui-page-subtitle mt-3">{ANALYSIS_PHASES[phaseIndex]}</p>
        <p className="mt-1 text-sm text-slate-500">
          Elapsed: {elapsedSeconds}s
        </p>
      </div>
    </section>
  );
}

export default function AnalysisPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const jdInputRef = useRef(null);
  const resumeInputRef = useRef(null);

  const [jdFile, setJdFile] = useState(null);
  const [resumeFile, setResumeFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [phaseIndex, setPhaseIndex] = useState(0);

  useEffect(() => {
    if (location.state?.analysisResult) {
      setAnalysis(location.state.analysisResult);
      setError("");
      cacheAnalysisForBack(location.state.analysisResult);
      return;
    }

    if (location.state?.processingError) {
      setError(location.state.processingError);
      return;
    }

    if (!location.state?.preserveAnalysis) return;

    try {
      const raw = sessionStorage.getItem(ANALYSIS_BACK_CACHE_KEY);
      if (!raw) return;

      const cached = JSON.parse(raw);
      if (cached?.analysis) {
        setAnalysis(cached.analysis);
        setError("");
        setLoading(false);
      }
    } catch {
      sessionStorage.removeItem(ANALYSIS_BACK_CACHE_KEY);
    }
  }, [location.state]);

  useEffect(() => {
    if (loading || analysis) return;

    try {
      const raw = sessionStorage.getItem(RESUME_UPGRADE_INTENT_KEY);
      if (!raw) return;

      const parsed = JSON.parse(raw);
      const createdAt = Number(parsed?.createdAt || 0);
      const intentRecordId = String(parsed?.recordId || "").trim();
      const ageMs = Date.now() - createdAt;

      if (!createdAt || ageMs > 15000) {
        sessionStorage.removeItem(RESUME_UPGRADE_INTENT_KEY);
        return;
      }

      sessionStorage.removeItem(RESUME_UPGRADE_INTENT_KEY);
      if (intentRecordId) {
        navigate(
          `/analysis/resume-upgrade?record=${encodeURIComponent(intentRecordId)}`,
          {
            replace: true,
            state: { analysisRecordId: intentRecordId },
          },
        );
        return;
      }

      navigate("/analysis/resume-upgrade", {
        replace: true,
        state: { analysisRecordId: "" },
      });
    } catch {
      sessionStorage.removeItem(RESUME_UPGRADE_INTENT_KEY);
    }
  }, [analysis, loading, navigate]);

  useEffect(() => {
    if (!loading) {
      setElapsedSeconds(0);
      setPhaseIndex(0);
      return;
    }

    const startedAt = Date.now();
    const intervalId = setInterval(() => {
      const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      setElapsedSeconds(elapsed);
      setPhaseIndex(
        Math.min(ANALYSIS_PHASES.length - 1, Math.floor(elapsed / 5)),
      );
    }, 1000);

    return () => clearInterval(intervalId);
  }, [loading]);

  useEffect(() => {
    if (error) {
      notifyError(error);
    }
  }, [error]);

  const matchScore = Number(analysis?.overall_score || 0);
  const matchedSkills = analysis?.matched_skills?.length
    ? analysis.matched_skills
    : analysis?.matched_keywords || [];
  const missingSkills = analysis?.missing_skills?.length
    ? analysis.missing_skills
    : analysis?.missing_keywords || [];
  const resumeHighlights = analysis?.resume_highlights || [];
  const strengthPoints = buildStrengthPoints(resumeHighlights);
  const displayCompany = deriveCompanyName(analysis, jdFile);
  const displayRole = deriveRoleName(analysis, jdFile);
  const displaySummary = buildDisplaySummary(analysis, matchScore);
  const weaknessPoints = analysis?.low_match_reasons?.length
    ? analysis.low_match_reasons
    : missingSkills.map(
        (skill) => `Limited proof for ${skill} in current resume.`,
      );
  const verdictLabel =
    analysis?.verdict ||
    (matchScore >= 70
      ? "Strong Match"
      : matchScore >= 45
        ? "Moderate Match"
        : "Low Match");
  const fitBadgeClass =
    matchScore >= 70
      ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-300"
      : matchScore >= 45
        ? "border-amber-500/50 bg-amber-500/15 text-amber-300"
        : "border-rose-500/50 bg-rose-500/15 text-rose-300";
  const skillCoverage = Math.round(
    (matchedSkills.length /
      Math.max(1, matchedSkills.length + missingSkills.length)) *
      100,
  );
  const analysisRecordId =
    extractAnalysisRecordId(analysis) ||
    (() => {
      try {
        const raw = sessionStorage.getItem(ANALYSIS_BACK_CACHE_KEY);
        if (!raw) return "";
        const cached = JSON.parse(raw);
        return extractAnalysisRecordId(cached?.analysis);
      } catch {
        return "";
      }
    })();
  const immediateFocus = (
    (analysis?.critical_missing_skills?.length
      ? analysis.critical_missing_skills
      : missingSkills) || []
  ).slice(0, 3);
  const strengthPreview = resumeHighlights.slice(0, 2);

  function resetForFreshAnalysis() {
    sessionStorage.removeItem(ANALYSIS_BACK_CACHE_KEY);
    setJdFile(null);
    setResumeFile(null);
    setAnalysis(null);
    setError("");
  }

  function cacheAnalysisForBack(snapshot) {
    if (!snapshot) return;
    sessionStorage.setItem(
      ANALYSIS_BACK_CACHE_KEY,
      JSON.stringify({ analysis: snapshot, savedAt: Date.now() }),
    );
  }

  async function runAnalysis() {
    if (!jdFile || !resumeFile) {
      setError("Please upload both JD and Resume before running analysis.");
      return;
    }

    setError("");
    navigate("/analysis/process", {
      state: {
        jdFile,
        resumeFile,
      },
    });
  }

  function openSkillUpdate(skill) {
    if (!analysisRecordId) return;

    cacheAnalysisForBack(analysis);

    const params = new URLSearchParams({ record: analysisRecordId });
    if (skill) {
      params.set("skill", skill);
    }
    navigate(`/analysis/skill-update?${params.toString()}`);
  }

  function openResumeUpgrade() {
    cacheAnalysisForBack(analysis);

    sessionStorage.setItem(
      RESUME_UPGRADE_INTENT_KEY,
      JSON.stringify({
        createdAt: Date.now(),
        recordId: analysisRecordId,
      }),
    );

    if (analysisRecordId) {
      const params = new URLSearchParams({ record: analysisRecordId });
      navigate(`/analysis/resume-upgrade?${params.toString()}`, {
        state: { analysisRecordId },
      });
      return;
    }

    navigate("/analysis/resume-upgrade", {
      state: { analysisRecordId: "" },
    });
  }

  return (
    <AppShell
      title="Analysis"
      subtitle="Upload JD + Resume, run AI match, then move into skill-gap roadmap."
      fullBleed
      darkShell
    >
      <input
        ref={jdInputRef}
        type="file"
        accept=".txt,.pdf,.docx"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0] || null;
          setJdFile(file);
          setAnalysis(null);
          sessionStorage.removeItem(ANALYSIS_BACK_CACHE_KEY);
          setError("");
          event.target.value = "";
        }}
      />

      <input
        ref={resumeInputRef}
        type="file"
        accept=".txt,.pdf,.docx"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0] || null;
          setResumeFile(file);
          setAnalysis(null);
          sessionStorage.removeItem(ANALYSIS_BACK_CACHE_KEY);
          setError("");
          event.target.value = "";
        }}
      />

      <div className="flex min-h-0 flex-1 flex-col space-y-6 overflow-y-auto pr-1">
        {!analysis && !loading && (
          <section className="flex min-h-[calc(100vh-170px)] flex-col justify-start rounded-3xl border-t-0 px-4 py-3 sm:px-6 sm:py-4 lg:justify-center">
            <div className="mx-auto max-w-4xl text-center">
              <p className="inline-flex items-center rounded-full border border-indigo-500/40 bg-indigo-500/10 px-3 py-1 text-xm font-semibold uppercase tracking-[0.14em] text-indigo-300">
                AI-Powered Career Accelerator
              </p>
              <h2 className="mt-3 text-2xl font-semibold leading-[1.2] tracking-tight text-slate-100 sm:text-3xl md:text-5xl">
                Bridge The Gap To Your{" "}
                <span className="bg-gradient-to-r from-indigo-300 via-violet-300 to-fuchsia-300 bg-clip-text text-transparent">
                  Dream Career
                </span>
              </h2>
              <p className="ui-page-subtitle mx-auto mt-2 max-w-xl text-sm">
                Upload your resume and job description to get skill-gap
                insights, role-fit analysis, and a guided learning plan.
              </p>
            </div>

            <div className="mt-6 grid items-center justify-center gap-6 lg:grid-cols-[minmax(0,300px)_auto_minmax(0,300px)]">
              <UploadFileCard
                title="Resume Content"
                subtitle="Your Experience"
                fileLabel="Resume"
                file={resumeFile}
                helper="Use PDF, DOCX, or TXT with role-focused achievements and projects."
                onUploadClick={() => resumeInputRef.current?.click()}
              />

              <div className="hidden lg:flex h-full items-center justify-center">
                <span className="inline-flex h-12 w-12 items-center justify-center rounded-full border border-indigo-400/40 bg-indigo-500/10 text-indigo-300 shadow-[0_0_30px_rgba(99,102,241,0.25)]">
                  <FiZap className="text-lg" />
                </span>
              </div>

              <UploadFileCard
                title="Job Description"
                subtitle="Target Role"
                fileLabel="Job Description"
                file={jdFile}
                helper="Upload the exact role JD so match score and missing skills are accurate."
                onUploadClick={() => jdInputRef.current?.click()}
              />
            </div>

            <div className="mt-9 flex flex-col items-center justify-center gap-3">
              <button
                type="button"
                disabled={!jdFile || !resumeFile}
                onClick={runAnalysis}
                className="inline-flex min-w-[220px] items-center justify-center gap-2 rounded-2xl bg-[linear-gradient(90deg,#7c8cff,#9c7cf8)] px-5 py-2.5 text-sm font-semibold text-slate-900 shadow-[0_18px_36px_rgba(99,102,241,0.35)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50 sm:min-w-[260px]"
              >
                Analyze Match
                <FiZap className="text-base" />
              </button>
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
                Powered by Neural Engine v4.0
              </p>
            </div>
          </section>
        )}

        {loading && (
          <LoadingScreen
            phaseIndex={phaseIndex}
            elapsedSeconds={elapsedSeconds}
          />
        )}

        {analysis && !loading && (
          <section className="flex-1 space-y-7">
            <article className="rounded-[30px] border border-slate-800  p-6 ">
              <div className="grid items-center gap-6 xl:grid-cols-[280px_1fr]">
                <div className="flex justify-center">
                  <div
                    className="relative h-52 w-52 rounded-full p-[10px]"
                    style={{
                      background: `conic-gradient(#8b9dff ${Math.max(0, Math.min(100, matchScore)) * 3.6}deg, rgba(100,116,139,0.25) 0deg)`,
                    }}
                  >
                    <div className="flex h-full w-full flex-col items-center justify-center rounded-full border border-slate-700 bg-[#0a112a] text-center">
                      <p className="text-6xl font-semibold tracking-tight text-slate-100">
                        {matchScore}%
                      </p>
                      <p className="mt-1 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
                        Match Score
                      </p>
                    </div>
                  </div>
                </div>

                <div>
                  <span
                    className={`inline-flex rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] ${fitBadgeClass}`}
                  >
                    AI Validated Analysis
                  </span>
                  <h2 className="mt-3 text-5xl font-semibold leading-none tracking-tight text-slate-100">
                    {displayCompany}
                  </h2>
                  <p className="mt-2 text-3xl font-medium text-indigo-300">
                    {displayRole}
                  </p>
                  <p className="mt-5 max-w-3xl text-lg leading-8 text-slate-300">
                    {displaySummary}
                  </p>

                  <div className="mt-5 flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={!analysisRecordId}
                      onClick={() => openSkillUpdate(missingSkills[0] || "")}
                      className="rounded-xl border border-indigo-400/50 bg-[linear-gradient(90deg,rgba(124,140,255,0.25),rgba(156,124,248,0.25))] px-5 py-2.5 text-sm font-semibold text-indigo-100 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Open Skill Roadmap
                    </button>
                    <button
                      type="button"
                      onClick={resetForFreshAnalysis}
                      className="rounded-xl border border-slate-600 bg-slate-900/60 px-5 py-2.5 text-sm font-semibold text-slate-200 transition hover:border-slate-400"
                    >
                      Return Analysis Hub
                    </button>
                  </div>
                </div>
              </div>
            </article>

            <div className="grid gap-5 xl:grid-cols-2">
              <article className="rounded-[26px] border border-slate-800  p-5 shadow-[0_18px_36px_rgba(2,8,24,0.35)]">
                <div className="flex items-center gap-2">
                  <FiCheckCircle className="text-base text-emerald-300" />
                  <h3 className="text-3xl font-semibold tracking-tight text-slate-100">
                    Resume Insights
                  </h3>
                </div>

                <div className="mt-4 space-y-5">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-emerald-300">
                      Key Strengths
                    </p>
                    <ul className="mt-2 space-y-2 text-sm text-slate-300">
                      {strengthPoints.slice(0, 3).map((point) => (
                        <li key={point} className="flex gap-2">
                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-emerald-300" />
                          <span>{point}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-rose-300">
                      Weaknesses
                    </p>
                    <ul className="mt-2 space-y-2 text-sm text-slate-300">
                      {weaknessPoints.slice(0, 3).map((point) => (
                        <li key={point} className="flex gap-2">
                          <span className="mt-1 h-1.5 w-1.5 rounded-full bg-rose-300" />
                          <span>{point}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </article>

              <article className="rounded-[26px] border border-slate-800  p-5 shadow-[0_18px_36px_rgba(2,8,24,0.35)]">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <FiTarget className="text-base text-indigo-300" />
                    <h3 className="text-2xl font-semibold tracking-tight text-slate-100">
                      Core JD Strengths
                    </h3>
                  </div>
                  <span className="rounded-md border border-indigo-500/40 bg-indigo-500/10 px-2 py-1 text-xs font-medium text-indigo-200">
                    {matchedSkills.length}
                  </span>
                </div>

                {matchedSkills.length ? (
                  <div className="mt-4 space-y-2">
                    {matchedSkills.slice(0, 5).map((skill) => (
                      <div
                        key={skill}
                        className="rounded-lg border border-slate-700/80 bg-slate-900/40 px-3 py-2 text-sm text-slate-200"
                      >
                        {skill}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-4 text-sm text-slate-400">
                    No strengths extracted yet.
                  </p>
                )}

                <p className="mt-4 text-xs text-slate-500">
                  Top matched skills identified from JD and resume alignment.
                </p>
              </article>
            </div>

            <section className="space-y-4">
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div>
                  <h3 className="text-4xl font-semibold tracking-tight text-slate-100">
                    Identified Skill Gaps
                  </h3>
                  <p className="mt-1 text-sm text-slate-400">
                    Personalized roadmaps generated by CareerPilot AI to bridge
                    your deficits.
                  </p>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {missingSkills.length ? (
                  missingSkills.map((skill, index) => {
                    const severity = getSeverityByIndex(
                      index,
                      missingSkills.length,
                    );
                    const severityClass =
                      severity === "HIGH"
                        ? "bg-rose-500/20 text-rose-300 border-rose-400/40"
                        : "bg-violet-500/20 text-violet-300 border-violet-400/40";

                    return (
                      <button
                        key={skill}
                        type="button"
                        onClick={() => openSkillUpdate(skill)}
                        className="group rounded-2xl border border-slate-700 bg-[#0d142e] p-4 text-left transition hover:border-indigo-400/60 hover:bg-slate-900/60"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className={`rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] ${severityClass}`}
                          >
                            {severity}
                          </span>
                          <FiArrowRight className="text-sm text-slate-500 transition group-hover:text-indigo-300" />
                        </div>
                        <p className="mt-3 text-2xl font-semibold leading-tight text-slate-100">
                          {skill}
                        </p>
                        <p className="mt-2 text-sm text-slate-400">
                          {buildSkillNote(skill, analysis)}
                        </p>
                        <span className="mt-4 inline-flex rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-xs font-medium text-slate-200">
                          View Roadmap
                        </span>
                      </button>
                    );
                  })
                ) : (
                  <div className="rounded-2xl border border-emerald-600/40 bg-emerald-500/10 p-4 sm:col-span-2 xl:col-span-4">
                    <p className="text-base font-semibold text-emerald-300">
                      No major skill gaps found
                    </p>
                    <p className="mt-1 text-sm text-slate-300">
                      Your resume aligns strongly with this role. Continue
                      interview practice to improve confidence.
                    </p>
                  </div>
                )}
              </div>
            </section>

            <section className="space-y-4">
              <h3 className="text-3xl font-semibold tracking-tight text-slate-100">
                Intelligence Quick Actions
              </h3>
              <div className="grid gap-4 md:grid-cols-3">
                <button
                  type="button"
                  onClick={() => navigate("/aiPrepare")}
                  className="group rounded-[22px] border border-slate-700 bg-[linear-gradient(145deg,rgba(42,63,105,0.35),rgba(9,18,44,0.85))] p-5 text-left transition hover:border-indigo-400/50"
                >
                  <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/20 text-indigo-300">
                    <FiTarget className="text-lg" />
                  </span>
                  <p className="mt-4 text-2xl font-semibold text-slate-100">
                    Start Interview Prep
                  </p>
                  <p className="mt-2 text-sm text-slate-400">
                    Simulate a high-pressure coding interview with CareerPilot
                    AI tailored to your role.
                  </p>
                  <span className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-indigo-300">
                    Go to Simulator <FiArrowRight className="text-sm" />
                  </span>
                </button>

                <button
                  type="button"
                  onClick={openResumeUpgrade}
                  className="group rounded-[22px] border border-slate-700 bg-[linear-gradient(145deg,rgba(79,70,229,0.2),rgba(9,18,44,0.85))] p-5 text-left transition hover:border-violet-400/50"
                >
                  <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/20 text-violet-300">
                    <FiPlay className="text-lg" />
                  </span>
                  <p className="mt-4 text-2xl font-semibold text-slate-100">
                    UpSkill Your Resume
                  </p>
                  <p className="mt-2 text-sm text-slate-400">
                    Apply AI-suggested rewrites for your experience section to
                    hit the JD keywords perfectly.
                  </p>
                  <span className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-violet-300">
                    Optimize Now <FiArrowRight className="text-sm" />
                  </span>
                </button>

                <button
                  type="button"
                  disabled={!analysisRecordId}
                  onClick={() =>
                    navigate(`/analysis/assessment?record=${analysisRecordId}`)
                  }
                  className="group rounded-[22px] border border-slate-700 bg-[linear-gradient(145deg,rgba(16,185,129,0.15),rgba(9,18,44,0.85))] p-5 text-left transition hover:border-emerald-400/50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/20 text-emerald-300">
                    <FiZap className="text-lg" />
                  </span>
                  <p className="mt-4 text-2xl font-semibold text-slate-100">
                    Enter Skill Lab
                  </p>
                  <p className="mt-2 text-sm text-slate-400">
                    Hands-on micro-projects focused specifically on your
                    identified gaps.
                  </p>
                  <span className="mt-5 inline-flex items-center gap-2 text-sm font-medium text-emerald-300">
                    Start Lab <FiArrowRight className="text-sm" />
                  </span>
                </button>
              </div>
            </section>
          </section>
        )}
      </div>
    </AppShell>
  );
}
