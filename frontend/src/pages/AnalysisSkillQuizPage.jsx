import { useEffect, useMemo, useState } from "react";
import {
  FiAward,
  FiArrowLeft,
  FiArrowUpRight,
  FiCheck,
  FiChevronLeft,
  FiDroplet,
  FiHelpCircle,
  FiLoader,
  FiSkipForward,
  FiTarget,
} from "react-icons/fi";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { evaluateSkillStepAssessment, startSkillStepAssessment } from "../api";
import AppShell from "../components/layout/AppShell";

function extractRecordId(returnTo) {
  try {
    const url = new URL(returnTo || "", window.location.origin);
    return url.searchParams.get("record") || "";
  } catch {
    return "";
  }
}

function normalizeQuestionText(text) {
  const raw = String(text || "").trim();
  if (!raw) return "";
  return raw.replace(/^In\s+.+?\s+assessment,\s*/i, "").replace(/^For\s+step\s+'.+?',\s*/i, "").trim();
}

function buildRelatedConcepts(question, selectedSkill) {
  const seed = [selectedSkill, ...(Array.isArray(question?.options) ? question.options : [])]
    .join(" ")
    .replace(/[^a-zA-Z0-9\s/+.-]/g, " ")
    .split(/\s+/)
    .map((item) => item.trim())
    .filter((item) => item.length >= 4);

  const seen = new Set();
  const concepts = [];
  for (const word of seed) {
    const key = word.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    concepts.push(word.charAt(0).toUpperCase() + word.slice(1));
    if (concepts.length >= 3) break;
  }

  if (concepts.length < 3) {
    return ["Firmware Verification", "MBR vs GPT", "Secure Boot"];
  }

  return concepts;
}

export default function AnalysisSkillQuizPage() {
  const navigate = useNavigate();
  const location = useLocation();

  const selectedSkill = location.state?.selectedSkill || "";
  const step = location.state?.step || null;
  const stepIndex = Number(location.state?.stepIndex || 0);
  const totalSteps = Number(location.state?.totalSteps || 1);
  const isSkillWideQuiz = Boolean(location.state?.coversAllSteps);
  const questionCount = Math.max(5, Math.min(20, Number(location.state?.questionCount || 10)));
  const returnTo = location.state?.returnTo || "/analysis/skill-update";
  const restoreState = location.state?.restoreState || null;
  const analysisRecordId =
    location.state?.analysisRecordId || extractRecordId(returnTo) || restoreState?.analysisRecordId || undefined;

  const [loading, setLoading] = useState(true);
  const [assessment, setAssessment] = useState(null);
  const [loadError, setLoadError] = useState("");

  const [phase, setPhase] = useState("quiz");
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answersByQuestionId, setAnswersByQuestionId] = useState({});
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    let active = true;

    async function loadStepAssessment() {
      if (!step || !selectedSkill) return;

      setLoading(true);
      setLoadError("");

      try {
        const payload = await startSkillStepAssessment({
          analysisRecordId,
          target: selectedSkill,
          stepTitle: step.title || `Step ${stepIndex + 1}`,
          stepDescription: step.description || "",
          actionItems: Array.isArray(step.actionItems) ? step.actionItems : [],
          questionCount,
        });

        if (!active) return;

        const questions = Array.isArray(payload?.questions) ? payload.questions : [];
        setAssessment(payload);
        setAnswersByQuestionId((prev) => {
          const next = {};
          questions.forEach((question) => {
            const qid = String(question?.question_id || "").trim();
            if (!qid) return;
            if (Number.isInteger(prev[qid])) {
              next[qid] = prev[qid];
            }
          });
          return next;
        });
      } catch (err) {
        if (!active) return;
        setLoadError(err.message || "Could not load this step assessment.");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    loadStepAssessment();

    return () => {
      active = false;
    };
  }, [analysisRecordId, selectedSkill, step, stepIndex, questionCount]);

  if (!step || !selectedSkill) {
    return <Navigate to={returnTo} replace state={{ restoreState }} />;
  }

  const questions = useMemo(() => (Array.isArray(assessment?.questions) ? assessment.questions : []), [assessment]);
  const currentQuestion = questions[currentIndex] || null;
  const currentQuestionId = String(currentQuestion?.question_id || "").trim();
  const selectedAnswer = currentQuestionId ? answersByQuestionId[currentQuestionId] : null;
  const answeredCount = questions.filter((question) => {
    const qid = String(question?.question_id || "").trim();
    return qid && Number.isInteger(answersByQuestionId[qid]);
  }).length;
  const questionProgressPct = questions.length ? Math.round(((currentIndex + 1) / questions.length) * 100) : 0;
  const hasSelection = Number.isInteger(selectedAnswer);
  const aiGuidanceText = currentQuestion?.explanation || "Choose the option that best reflects practical and technically accurate reasoning.";
  const relatedConcepts = useMemo(
    () => buildRelatedConcepts(currentQuestion, selectedSkill),
    [currentQuestion, selectedSkill]
  );
  const actionLabel = currentIndex >= questions.length - 1 ? "Finish Quiz" : "Submit Answer";

  function chooseAnswer(optionIndex) {
    if (!currentQuestionId) return;
    setAnswersByQuestionId((prev) => ({
      ...prev,
      [currentQuestionId]: optionIndex,
    }));
  }

  function skipQuestion() {
    if (currentIndex < questions.length - 1) {
      setCurrentIndex((prev) => prev + 1);
    }
  }

  function handleNext() {
    if (currentIndex < questions.length - 1) {
      setCurrentIndex((prev) => prev + 1);
    }
  }

  function handlePrevious() {
    if (currentIndex > 0) {
      setCurrentIndex((prev) => prev - 1);
    }
  }

  function handleSubmitOrNext() {
    if (currentIndex >= questions.length - 1) {
      submitAssessment();
      return;
    }
    handleNext();
  }

  async function submitAssessment() {
    if (!assessment?.session_id) return;

    setSubmitting(true);
    setSubmitError("");

    try {
      const payload = await evaluateSkillStepAssessment(
        assessment.session_id,
        questions
          .map((question) => {
            const qid = String(question?.question_id || "").trim();
            const selectedOptionIndex = qid ? answersByQuestionId[qid] : null;
            if (!qid || !Number.isInteger(selectedOptionIndex)) return null;
            return {
              question_id: qid,
              selected_option_index: selectedOptionIndex,
            };
          })
          .filter(Boolean)
      );

      setResult(payload);
      setPhase("result");
    } catch (err) {
      setSubmitError(err.message || "Could not evaluate this step quiz. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  function finalizeAndBack() {
    const scorePercent = Number(result?.score_percentage || 0);
    const passed = Boolean(result?.passed);

    navigate(returnTo, {
      replace: true,
      state: {
        restoreState,
        quizResult: {
          attemptId: Date.now(),
          selectedSkill,
          stepIndex,
          scorePercent,
          passed,
          coversAllSteps: isSkillWideQuiz,
          totalSteps,
        },
      },
    });
  }

  return (
    <AppShell title="Skill Quiz" subtitle="Step-by-step checkpoint" fullBleed darkShell>
      <div className="flex min-h-0 flex-1 overflow-y-auto ">
        <main className="mx-auto w-full max-w-6xl px-6 pb-10 pt-3 lg:pb-14 lg:pt-4">
          <div className="mb-2 flex justify-end">
            <button
              type="button"
              onClick={() => navigate(returnTo, { replace: true, state: { restoreState } })}
              className="inline-flex items-center gap-2 rounded-xl border border-[#2d3240] bg-[#0c1018] px-3.5 py-2 text-sm font-medium text-[#d8dcec] transition hover:border-[#4a5164]"
            >
              <FiArrowLeft className="text-sm" />
              Back
            </button>
          </div>

          {loading && (
            <section className="rounded-[26px] border-t-0 bg-slate-400/10  p-10 text-center">
              <FiLoader className="mx-auto animate-spin text-2xl text-[#a7a5ff]" />
              <p className="mt-3 text-sm text-[#a3a8b6] ">Generating AI quiz questions...</p>
            </section>
          )}

          {!loading && loadError && (
            <section className="rounded-[26px] border border-red-400/40 bg-red-500/10 p-6 text-sm text-red-200">
              {loadError}
            </section>
          )}

          {!loading && !loadError && phase === "quiz" && currentQuestion && (
            <div
              key={currentQuestion.question_id || `q-${currentIndex}`}
              className="grid grid-cols-1 items-start gap-10 lg:grid-cols-12 lg:gap-8"
              style={{ animation: "fadeSlide 280ms ease-out" }}
            >
              <section className="space-y-10 lg:col-span-8">
                <div className="space-y-4">
                  <div className="flex items-end justify-between">
                    <span className="text-xs uppercase tracking-[0.16em] text-[#8f95aa]">
                      Question {currentIndex + 1} of {questions.length}
                    </span>
                    <span className="text-2xl font-bold text-[#a7a5ff]">{questionProgressPct}%</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-[#16181f]">
                    <div
                      className="h-full rounded-full bg-[linear-gradient(135deg,#a7a5ff_0%,#645efb_100%)] shadow-[0_0_20px_rgba(167,165,255,0.3)]"
                      style={{ width: `${Math.max(8, questionProgressPct)}%` }}
                    />
                  </div>
                </div>

                <div className="space-y-5" style={{ animation: "fadeSlide 320ms ease-out", animationDelay: "30ms", animationFillMode: "both" }}>
                  <h2 className="text-4xl font-extrabold leading-tight tracking-tight text-white md:text-3xl">
                    {normalizeQuestionText(currentQuestion.question)}
                  </h2>
                  <p className="max-w-2xl text-lg leading-relaxed text-[#a3a8b6]">
                    Think carefully before selecting the most accurate technical answer for {selectedSkill}.
                  </p>
                </div>

                <div className="grid grid-cols-1 gap-4">
                  {currentQuestion.options.map((option, optionIndex) => {
                    const isSelected = selectedAnswer === optionIndex;
                    const optionLabel = String.fromCharCode(65 + optionIndex);
                    return (
                      <button
                        key={`${currentQuestion.question_id}-${optionIndex}`}
                        type="button"
                        onClick={() => chooseAnswer(optionIndex)}
                        className={`group flex items-center justify-between rounded-4xl border p-6 text-left transition-all duration-300 ${
                          isSelected
                            ? "border-[#a7a5ff] bg-[#a7a5ff0f] outline outline-2 outline-[#a7a5ff]"
                            : "border-[#2a2d36] bg-[rgba(38,38,38,0.4)] hover:bg-[#242833]"
                        }`}
                        style={{
                          animation: "fadeSlide 320ms ease-out",
                          animationDelay: `${90 + optionIndex * 45}ms`,
                          animationFillMode: "both",
                        }}
                      >
                        <span className="flex items-center gap-6">
                          <span
                            className={`inline-flex h-10 w-10 items-center justify-center rounded-md border text-base font-bold ${
                              isSelected
                                ? "border-[#a7a5ff] bg-[#a7a5ff] text-[#1c00a0]"
                                : "border-[#3a3f50] bg-[#06070b] text-[#a7a5ff] group-hover:border-[#a7a5ff]"
                            }`}
                          >
                            {optionLabel}
                          </span>
                          <span className={`text-base font-medium ${isSelected ? "text-white" : "text-[#e3e6f1]"}`}>{option}</span>
                        </span>

                        {isSelected ? (
                          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-[#a7a5ff] text-[#1c00a0]">
                            <FiCheck className="text-sm" />
                          </span>
                        ) : (
                          <span className="h-6 w-6 rounded-full border-2 border-[#494847] transition-colors group-hover:border-[#a7a5ff]" />
                        )}
                      </button>
                    );
                  })}
                </div>

                <div className="flex flex-col items-center justify-between gap-6 pt-1 sm:flex-row">
                  <div className="flex items-center gap-4">
                    <button
                      type="button"
                      onClick={handlePrevious}
                      disabled={currentIndex <= 0}
                      className="inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium text-[#9aa0b3] transition hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <FiChevronLeft className="text-sm" />
                      Previous Question
                    </button>
                    <button
                      type="button"
                      onClick={skipQuestion}
                      disabled={currentIndex >= questions.length - 1}
                      className="rounded-full px-5 py-2.5 text-sm font-medium text-[#9aa0b3] transition hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Skip
                    </button>
                  </div>

                  <button
                    type="button"
                    onClick={handleSubmitOrNext}
                    disabled={submitting || !hasSelection}
                    className="rounded-full border border-transparent bg-[linear-gradient(135deg,#a7a5ff_0%,#645efb_100%)] px-11 py-4 text-sm font-bold text-[#1c00a0] shadow-[0_0_30px_rgba(100,94,251,0.45)] transition-all hover:shadow-[0_0_45px_rgba(100,94,251,0.6)] disabled:cursor-not-allowed disabled:opacity-55"
                  >
                    {submitting ? "Submitting..." : actionLabel}
                  </button>
                </div>

                {submitError && <p className="text-sm text-red-300">{submitError}</p>}
              </section>

              <aside className="space-y-6 lg:col-span-4">
                <div className="rounded-3xl border border-[#a7a5ff1f] bg-[rgba(38,38,38,0.4)] p-6 shadow-[inset_0_1px_0_0_rgba(167,165,255,0.15)]">
                  <div className="flex items-center gap-3">
                    <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-[#8f60fa33] text-[#ac8aff]">
                      <FiHelpCircle className="text-base" />
                    </span>
                    <div>
                      <h3 className="text-lg font-bold text-white">AI Guidance</h3>
                      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#9aa0b3]">Skill Booster</p>
                    </div>
                  </div>

                  <div className="mt-5 rounded-xl bg-[#000000] p-4">
                    <p className="text-sm leading-relaxed text-[#a3a8b6]">{aiGuidanceText}</p>
                  </div>

                  <div className="mt-5 space-y-3">
                    <h4 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#9aa0b3]">Related Concepts</h4>
                    <div className="flex flex-wrap gap-2">
                      {relatedConcepts.map((concept) => (
                        <span key={concept} className="rounded-full bg-[#262626] px-3 py-1 text-[10px] font-medium text-[#a3a8b6]">
                          {concept}
                        </span>
                      ))}
                    </div>
                  </div>

                  
                </div>
              </aside>
            </div>
          )}

          {!loading && !loadError && phase === "quiz" && !currentQuestion && (
            <section className="rounded-[26px] border border-amber-400/40 bg-amber-500/10 p-6 text-sm text-amber-200">
              Quiz questions are not available for this skill yet. Please go back and start the quiz again.
            </section>
          )}
          {!loading && !loadError && phase === "result" && (
            <section className="rounded-[26px] border border-[rgba(100,116,139,0.4)]  p-6 text-center shadow-[0_20px_44px_rgba(2,8,24,0.45)]">
              <span className="mx-auto inline-flex h-16 w-16 items-center justify-center rounded-full border border-indigo-400/50  text-indigo-300">
                <FiTarget className="text-2xl" />
              </span>

              <h2 className="mt-4 text-3xl font-semibold tracking-tight text-slate-100">Quiz Complete</h2>
              <p className="mt-2 text-lg text-slate-200">Score: {result?.score_percentage || 0}%</p>

              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <div className="rounded-xl border border-slate-700/80 bg-slate-900/50 px-3 py-2">
                  <p className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Correct</p>
                  <p className="mt-1 text-lg font-semibold text-slate-100">{result?.correct_count ?? 0}</p>
                </div>
                <div className="rounded-xl border border-slate-700/80 bg-slate-900/50 px-3 py-2">
                  <p className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Total</p>
                  <p className="mt-1 text-lg font-semibold text-slate-100">{result?.total_questions ?? 0}</p>
                </div>
                <div className="rounded-xl border border-slate-700/80 bg-slate-900/50 px-3 py-2">
                  <p className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Status</p>
                  <p className={`mt-1 text-lg font-semibold ${result?.passed ? "text-emerald-300" : "text-amber-300"}`}>
                    {result?.passed ? "Passed" : "Retry"}
                  </p>
                </div>
              </div>

              <p className={`mt-3 text-sm ${result?.passed ? "text-emerald-300" : "text-amber-300"}`}>
                {result?.motivation || "Assessment completed."}
              </p>
              <p className="mt-2 text-xs uppercase tracking-[0.14em] text-slate-500">
                You can proceed to any roadmap step. Quiz is for confidence tracking.
              </p>

              <button
                type="button"
                onClick={finalizeAndBack}
                className="mt-6 inline-flex items-center gap-2 rounded-xl border border-indigo-400/50 bg-[linear-gradient(90deg,rgba(124,140,255,0.35),rgba(156,124,248,0.35))] px-5 py-2.5 text-sm font-semibold text-indigo-100 transition hover:brightness-110"
              >
                <FiAward className="text-sm" />
                Back to Skill Page
              </button>
            </section>
          )}
        </main>
      </div>
    </AppShell>
  );
}
