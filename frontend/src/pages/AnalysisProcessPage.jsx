import { useEffect, useMemo, useRef, useState } from "react";
import { FiCheckCircle, FiShield, FiZap } from "react-icons/fi";
import { useLocation, useNavigate } from "react-router-dom";

import AppShell from "../components/layout/AppShell";
import { analyzeResumeMatch } from "../api";

const ANALYSIS_BACK_CACHE_KEY = "jarvis_analysis_back_cache";

const PROCESS_STEPS = [
  {
    title: "Scanning document structure",
    subtitle: "Extracting clean content from JD and resume",
  },
  {
    title: "Matching skills & experience",
    subtitle: "Aligning evidence against role requirements",
  },
  {
    title: "Generating insights",
    subtitle: "Preparing score, gaps, and strategy cards",
  },
];

export default function AnalysisProcessPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const startedRef = useRef(false);

  const jdFile = location.state?.jdFile || null;
  const resumeFile = location.state?.resumeFile || null;

  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const phaseIndex = useMemo(() => {
    return Math.min(PROCESS_STEPS.length - 1, Math.floor(elapsedSeconds / 4));
  }, [elapsedSeconds]);

  useEffect(() => {
    const intervalId = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);

    return () => clearInterval(intervalId);
  }, []);

  useEffect(() => {
    if (!jdFile || !resumeFile) {
      navigate("/analysis", {
        replace: true,
        state: {
          processingError: "Please upload both JD and Resume before running analysis.",
        },
      });
      return;
    }

    if (startedRef.current) return;
    startedRef.current = true;

    async function runProcessing() {
      try {
        const result = await analyzeResumeMatch(jdFile, resumeFile);
        sessionStorage.setItem(
          ANALYSIS_BACK_CACHE_KEY,
          JSON.stringify({ analysis: result, savedAt: Date.now() })
        );

        navigate("/analysis", {
          replace: true,
          state: {
            analysisResult: result,
            preserveAnalysis: true,
          },
        });
      } catch (err) {
        navigate("/analysis", {
          replace: true,
          state: {
            processingError: err?.message || "Analysis failed",
          },
        });
      }
    }

    runProcessing();
  }, [jdFile, resumeFile, navigate]);

  return (
    <AppShell
      title="Analysis"
      subtitle="Processing resume and JD alignment"
      fullBleed
      darkShell
    >
      <section className="flex min-h-[calc(100vh-220px)] items-center justify-center px-4 py-8">
        <div className="w-full max-w-3xl rounded-[28px] border border-slate-800 bg-[linear-gradient(160deg,rgba(10,18,46,0.95),rgba(6,11,30,0.98))] p-6 shadow-[0_24px_52px_rgba(2,8,24,0.45)] sm:p-8">
          <div className="text-center">
            <div className="mx-auto flex h-24 w-24 items-center justify-center rounded-full border border-slate-700 bg-slate-900/50">
              <div className="absolute h-24 w-24 animate-spin rounded-full border-4 border-indigo-400/20 border-t-indigo-300" />
              <span className="relative inline-flex h-14 w-14 items-center justify-center rounded-full border border-indigo-400/40 bg-indigo-500/10 text-indigo-300">
                <FiZap className="text-2xl" />
              </span>
            </div>

            <h2 className="mt-8 text-4xl font-semibold tracking-tight text-slate-100">Analyzing your resume...</h2>
            <p className="mt-3 text-base text-slate-300">
              {PROCESS_STEPS[phaseIndex].subtitle}
            </p>
          </div>

          <div className="mt-8 space-y-4">
            {PROCESS_STEPS.map((step, index) => {
              const completed = index < phaseIndex;
              const processing = index === phaseIndex;
              const queued = index > phaseIndex;
              const activeFill = 45 + (elapsedSeconds % 4) * 12;
              const width = completed ? 100 : processing ? Math.min(activeFill, 90) : 6;

              return (
                <div key={step.title} className="space-y-2">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <div className="flex items-center gap-2">
                      {completed ? (
                        <FiCheckCircle className="text-indigo-300" />
                      ) : (
                        <span
                          className={`inline-flex h-4 w-4 rounded-full border ${
                            processing
                              ? "border-indigo-300 bg-indigo-500/25"
                              : "border-slate-600 bg-slate-800"
                          }`}
                        />
                      )}
                      <p className={`${completed || processing ? "text-slate-100" : "text-slate-500"}`}>
                        {step.title}
                      </p>
                    </div>
                    <p className={`${completed ? "text-indigo-300" : processing ? "text-slate-300" : "text-slate-500"}`}>
                      {completed ? "Completed" : processing ? "Processing..." : "Queued"}
                    </p>
                  </div>

                  <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                    <div
                      className="h-full rounded-full bg-[linear-gradient(90deg,#7c8cff,#9c7cf8)] transition-all duration-500"
                      style={{ width: `${width}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          <p className="mt-8 flex items-center justify-center gap-2 text-sm text-slate-400">
            <FiShield className="text-slate-300" />
            Your data is encrypted and private
          </p>
        </div>
      </section>
    </AppShell>
  );
}
