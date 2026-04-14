import { useEffect, useMemo, useState } from "react";
import { FiArrowLeft, FiArrowRight, FiCheckCircle, FiFlag, FiPlay, FiSend, FiXCircle } from "react-icons/fi";
import { useNavigate, useSearchParams } from "react-router-dom";

import AppShell from "../components/layout/AppShell";
import {
  evaluateHrPractice,
  evaluateMcqAssessment,
  evaluateResumeAssessment,
  startHrPractice,
  startMcqAssessment,
  startResumeAssessment,
} from "../api";
import { notifyError } from "../utils/toast";

export default function AnalysisAssessmentPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const analysisRecordId = searchParams.get("record") || "";

  const [questionCount, setQuestionCount] = useState(10);
  const [technicalRoleTrack, setTechnicalRoleTrack] = useState("General Professional Role");
  const [startingTechnical, setStartingTechnical] = useState(false);
  const [technicalSubmitting, setTechnicalSubmitting] = useState(false);
  const [technicalQuestions, setTechnicalQuestions] = useState([]);
  const [technicalSelectedAnswers, setTechnicalSelectedAnswers] = useState({});
  const [technicalQuestionIndex, setTechnicalQuestionIndex] = useState(0);
  const [technicalEvaluation, setTechnicalEvaluation] = useState(null);

  const [resumeRoleTrack, setResumeRoleTrack] = useState("General Professional Role");
  const [resumeLoadingQuestions, setResumeLoadingQuestions] = useState(false);
  const [resumeSubmitting, setResumeSubmitting] = useState(false);
  const [resumeQuestions, setResumeQuestions] = useState([]);
  const [resumeAnswers, setResumeAnswers] = useState([]);
  const [resumeQuestionIndex, setResumeQuestionIndex] = useState(0);
  const [resumeEvaluation, setResumeEvaluation] = useState(null);

  const [hrLoadingQuestions, setHrLoadingQuestions] = useState(false);
  const [hrSubmitting, setHrSubmitting] = useState(false);
  const [hrQuestions, setHrQuestions] = useState([]);
  const [hrAnswers, setHrAnswers] = useState([]);
  const [hrQuestionIndex, setHrQuestionIndex] = useState(0);
  const [hrEvaluation, setHrEvaluation] = useState(null);
  const [assessmentStage, setAssessmentStage] = useState("setup");

  const [error, setError] = useState("");

  useEffect(() => {
    if (error) {
      notifyError(error);
    }
  }, [error]);

  const technicalAnsweredCount = useMemo(() => {
    return technicalQuestions.filter((item) => Number.isInteger(technicalSelectedAnswers[item.question_id])).length;
  }, [technicalQuestions, technicalSelectedAnswers]);

  const resumeAnsweredCount = useMemo(() => {
    return resumeAnswers.filter((value) => value.trim().length >= 12).length;
  }, [resumeAnswers]);

  const canSubmitTechnical =
    technicalQuestions.length > 0 &&
    technicalAnsweredCount === technicalQuestions.length &&
    !technicalSubmitting;

  const canSubmitResume =
    resumeQuestions.length > 0 &&
    resumeAnsweredCount === resumeQuestions.length &&
    !resumeSubmitting;

  async function handleStartTechnicalRound() {
    if (!analysisRecordId) return;

    setStartingTechnical(true);
    setError("");
    setTechnicalEvaluation(null);
    setAssessmentStage("setup");
    setResumeRoleTrack("General Professional Role");
    setResumeQuestions([]);
    setResumeAnswers([]);
    setResumeQuestionIndex(0);
    setResumeEvaluation(null);
    setHrQuestions([]);
    setHrAnswers([]);
    setHrQuestionIndex(0);
    setHrEvaluation(null);
    try {
      const payload = await startMcqAssessment(analysisRecordId, questionCount);
      const loadedQuestions = Array.isArray(payload.questions) ? payload.questions : [];
      setTechnicalRoleTrack(payload.role_track || "General Professional Role");
      setTechnicalQuestions(loadedQuestions);
      setTechnicalSelectedAnswers(
        loadedQuestions.reduce((acc, item) => {
          acc[item.question_id] = null;
          return acc;
        }, {})
      );
      setTechnicalQuestionIndex(0);
      setAssessmentStage("round1_questions");
    } catch (err) {
      setError(err.message || "Could not generate technical assessment questions.");
    } finally {
      setStartingTechnical(false);
    }
  }

  function selectTechnicalOption(questionId, optionIndex) {
    setTechnicalSelectedAnswers((prev) => ({
      ...prev,
      [questionId]: optionIndex,
    }));
  }

  function updateResumeAnswer(index, value) {
    setResumeAnswers((prev) => prev.map((item, itemIndex) => (itemIndex === index ? value : item)));
  }

  async function handleSubmitTechnical() {
    if (!canSubmitTechnical || !analysisRecordId) return;

    setTechnicalSubmitting(true);
    setError("");
    try {
      const answers = technicalQuestions.map((item) => ({
        question_id: item.question_id,
        selected_option_index: technicalSelectedAnswers[item.question_id],
      }));
      const result = await evaluateMcqAssessment(analysisRecordId, answers);
      setTechnicalEvaluation(result);
      setAssessmentStage("round1_result");
    } catch (err) {
      setError(err.message || "Could not evaluate technical round answers.");
    } finally {
      setTechnicalSubmitting(false);
    }
  }

  async function loadResumeRound() {
    if (!analysisRecordId || resumeQuestions.length) return;
    setAssessmentStage("round2_loading");
    setResumeLoadingQuestions(true);
    setError("");
    try {
      const payload = await startResumeAssessment(analysisRecordId, questionCount);
      const nextQuestions = Array.isArray(payload.questions) ? payload.questions : [];
      setResumeRoleTrack(payload.role_track || "General Professional Role");
      setResumeQuestions(nextQuestions);
      setResumeAnswers(nextQuestions.map(() => ""));
      setResumeQuestionIndex(0);
      setAssessmentStage("round2_questions");
    } catch (err) {
      setAssessmentStage("round1_result");
      setError(err.message || "Could not load resume skills assessment questions.");
    } finally {
      setResumeLoadingQuestions(false);
    }
  }

  async function handleSubmitResume() {
    if (!analysisRecordId || !canSubmitResume) return;

    setResumeSubmitting(true);
    setError("");
    try {
      const answers = resumeQuestions.map((item, index) => ({
        question_id: item.question_id,
        question: item.question,
        answer: resumeAnswers[index].trim(),
      }));
      const result = await evaluateResumeAssessment(analysisRecordId, answers);
      setResumeEvaluation(result);
      setAssessmentStage("round2_result");
    } catch (err) {
      setError(err.message || "Could not evaluate resume round answers.");
    } finally {
      setResumeSubmitting(false);
    }
  }

  async function loadHrRound() {
    if (!analysisRecordId || hrQuestions.length) return;
    setAssessmentStage("round3_loading");
    setHrLoadingQuestions(true);
    setError("");
    try {
      const payload = await startHrPractice(analysisRecordId);
      const nextQuestions = Array.isArray(payload.questions) ? payload.questions : [];
      setHrQuestions(nextQuestions);
      setHrAnswers(nextQuestions.map(() => ""));
      setHrQuestionIndex(0);
      setAssessmentStage("round3_questions");
    } catch (err) {
      setAssessmentStage("round2_result");
      setError(err.message || "Could not load predefined HR round questions.");
    } finally {
      setHrLoadingQuestions(false);
    }
  }

  function updateHrAnswer(index, value) {
    setHrAnswers((prev) => prev.map((item, itemIndex) => (itemIndex === index ? value : item)));
  }

  const hrAnsweredCount = useMemo(
    () => hrAnswers.filter((value) => value.trim().length >= 12).length,
    [hrAnswers]
  );

  const canSubmitHr = hrQuestions.length > 0 && hrAnsweredCount === hrQuestions.length && !hrSubmitting;

  const technicalCurrentQuestion = technicalQuestions[technicalQuestionIndex] || null;
  const resumeCurrentQuestion = resumeQuestions[resumeQuestionIndex] || null;
  const hrCurrentQuestion = hrQuestions[hrQuestionIndex] || null;

  const technicalCurrentAnswered = technicalCurrentQuestion
    ? Number.isInteger(technicalSelectedAnswers[technicalCurrentQuestion.question_id])
    : false;
  const resumeCurrentAnswered = (resumeAnswers[resumeQuestionIndex] || "").trim().length >= 12;
  const hrCurrentAnswered = (hrAnswers[hrQuestionIndex] || "").trim().length >= 12;

  function getProgressPercent(index, total) {
    if (!total) return 0;
    return Math.round(((index + 1) / total) * 100);
  }

  const technicalWrongAnswers = technicalEvaluation?.results?.filter((item) => !item.is_correct) || [];
  const overallScore = useMemo(() => {
    if (!technicalEvaluation || !resumeEvaluation || !hrEvaluation) return null;
    return Math.round(
      (
        Number(technicalEvaluation.score_percentage || 0) +
        Number(resumeEvaluation.overall_score || 0) +
        Number(hrEvaluation.overall_score || 0)
      ) / 3
    );
  }, [technicalEvaluation, resumeEvaluation, hrEvaluation]);

  async function handleSubmitHr() {
    if (!analysisRecordId || !canSubmitHr) return;

    setHrSubmitting(true);
    setError("");
    try {
      const answers = hrQuestions.map((question, index) => ({
        question_id: question.question_id,
        question: question.question,
        answer: hrAnswers[index].trim(),
      }));
      const result = await evaluateHrPractice(analysisRecordId, answers);
      setHrEvaluation(result);
      setAssessmentStage("final");
    } catch (err) {
      setError(err.message || "Could not evaluate HR round answers.");
    } finally {
      setHrSubmitting(false);
    }
  }

  const glassPanelClass =
    "rounded-[28px] border border-[#2b2f38] bg-[rgba(22,26,33,0.6)] backdrop-blur-[24px] shadow-[0_18px_42px_rgba(2,6,23,0.45)]";
  const questionCardClass = "rounded-2xl border border-[#3a404f] bg-[rgba(16,19,26,0.9)]";
  const stageRoleLabel =
    assessmentStage.startsWith("round2") ? resumeRoleTrack : technicalRoleTrack;

  return (
    <AppShell
      title="JD MCQ Assessment"
      subtitle="Round 1: Technical JD, Round 2: Resume Skills, Round 3: HR Interview"
      fullBleed
      darkShell
    >
      <div className="relative h-full min-h-0 space-y-6 overflow-x-hidden overflow-y-auto pb-10 pr-1">
        <div className="pointer-events-none absolute -left-24 top-20 h-72 w-72 rounded-full bg-[#85adff0f] blur-[90px]" />
        <div className="pointer-events-none absolute -bottom-10 right-2 h-72 w-72 rounded-full bg-[#ac8aff0d] blur-[110px]" />

        <div className="relative flex justify-end">
          <button
            type="button"
            onClick={() => navigate("/analysis", { state: { preserveAnalysis: true } })}
            className="inline-flex items-center gap-2 rounded-full border border-[#3c4252] bg-[#0c1018] px-4 py-2 text-sm font-medium text-slate-100 transition hover:border-[#68718a]"
          >
            <FiArrowLeft className="text-sm" />
            Back To Analysis
          </button>
        </div>

        {!analysisRecordId && (
          <div className="rounded-2xl border border-amber-400/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            Open this page from analysis result so assessment can use your uploaded JD.
          </div>
        )}

        {analysisRecordId && assessmentStage === "setup" && (
          <section className={`${glassPanelClass} mx-auto max-w-4xl p-6 md:p-10`}>
            <div className="text-center">
              <div className="flex items-center justify-center gap-3">
                <span className="rounded-full bg-[#22262f] px-3 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-[#85adff]">
                  Phase 01
                </span>
                <div className="h-px w-12 bg-[#45484f55]" />
                <span className="text-[10px] uppercase tracking-[0.16em] text-[#a9abb3]">
                  Target Role: {stageRoleLabel}
                </span>
              </div>
              <h2 className="mt-4 text-4xl font-extrabold tracking-tight text-[#ecedf6] md:text-5xl">
                Round 1: Technical Assessment
              </h2>
              <p className="mx-auto mt-3 max-w-2xl text-base leading-relaxed text-[#a9abb3]">
                Evaluate your core technical competency through AI-generated questions tailored to your target role.
              </p>
            </div>

            <div className="mt-8 rounded-3xl border border-[#45484f33] bg-[rgba(16,19,26,0.85)] p-6 md:p-8">
              <h3 className="text-center text-xl font-bold text-[#ecedf6]">Technical Round Setup</h3>
              <p className="mt-3 text-center text-xs font-bold uppercase tracking-[0.14em] text-[#a9abb3]">
                Question Volume Selection
              </p>

              <div className="mt-6 grid gap-4 md:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setQuestionCount(10)}
                  className={`rounded-2xl border p-5 text-left transition-all ${
                    questionCount === 10
                      ? "border-[#85adff66] bg-[#85adff12] shadow-[0_0_20px_rgba(133,173,255,0.14)]"
                      : "border-[#45484f33] bg-[#161a21] hover:border-[#85adff4d]"
                  }`}
                >
                  <p className="text-2xl font-bold text-[#ecedf6]">10 Questions</p>
                  <p className="mt-1 text-sm text-[#a9abb3]">Estimated duration: 15 mins. Focused sprint on core paradigms.</p>
                </button>

                <button
                  type="button"
                  onClick={() => setQuestionCount(20)}
                  className={`rounded-2xl border p-5 text-left transition-all ${
                    questionCount === 20
                      ? "border-[#85adff66] bg-[#85adff12] shadow-[0_0_20px_rgba(133,173,255,0.14)]"
                      : "border-[#45484f33] bg-[#161a21] hover:border-[#85adff4d]"
                  }`}
                >
                  <p className="text-2xl font-bold text-[#ecedf6]">20 Questions</p>
                  <p className="mt-1 text-sm text-[#a9abb3]">Estimated duration: 35 mins. Deep-dive into architectural edge cases.</p>
                </button>
              </div>

              <button
                type="button"
                onClick={handleStartTechnicalRound}
                disabled={startingTechnical}
                className="mt-8 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-[linear-gradient(90deg,#85adff,#ac8aff)] px-5 py-4 text-base font-bold text-[#002c66] shadow-[0_0_30px_rgba(133,173,255,0.3)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <FiPlay className="text-sm" />
                {startingTechnical ? "Generating Technical Questions..." : "Start Technical Round"}
              </button>

              <p className="mt-5 text-center text-[10px] uppercase tracking-[0.16em] text-[#a9abb3]">
                Session will be recorded for intelligence mapping
              </p>
            </div>

            <div className="mx-auto mt-6 max-w-2xl rounded-2xl border border-[#45484f33] bg-[#10131a] p-4 text-xs text-[#a9abb3]">
              Questions are generated by the Skill Lab engine. Ensure you are in a quiet environment.
            </div>
          </section>
        )}

        {assessmentStage === "round1_questions" && technicalQuestions.length > 0 && (
          <section className={`${glassPanelClass} mx-auto max-w-4xl p-5 md:p-7`}>
            <div className="mx-auto max-w-3xl">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#a9abb3]">Technical Foundation</p>
                  <p className="mt-1 text-2xl font-semibold text-[#ecedf6]">
                    Question {technicalQuestionIndex + 1} of {technicalQuestions.length}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-xl font-bold text-[#85adff]">{getProgressPercent(technicalQuestionIndex, technicalQuestions.length)}%</p>
                  <p className="text-xs uppercase tracking-[0.16em] text-[#a9abb3]">Complete</p>
                </div>
              </div>

              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#1b2330]">
                <div
                  className="h-full rounded-full bg-[linear-gradient(90deg,#85adff,#ac8aff)] transition-all duration-300"
                  style={{ width: `${getProgressPercent(technicalQuestionIndex, technicalQuestions.length)}%` }}
                />
              </div>

              {technicalCurrentQuestion && (
                <div className="mt-5 rounded-3xl border border-[#303746] bg-[rgba(14,18,27,0.92)] p-5 md:p-7">
                  <p className="text-2xl font-semibold leading-tight text-[#ecedf6]">
                    {technicalCurrentQuestion.question}
                  </p>

                  <div className="mt-6 space-y-3">
                    {(technicalCurrentQuestion.options || []).map((option, optionIndex) => {
                      const checked = technicalSelectedAnswers[technicalCurrentQuestion.question_id] === optionIndex;
                      const label = String.fromCharCode(65 + optionIndex);
                      return (
                        <button
                          type="button"
                          key={`${technicalCurrentQuestion.question_id}-${optionIndex}`}
                          onClick={() => selectTechnicalOption(technicalCurrentQuestion.question_id, optionIndex)}
                          className={`group flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left text-base transition ${
                            checked
                              ? "border-[#85adff66] bg-[#85adff12] text-[#ecedf6]"
                              : "border-[#2f3441] bg-[#111722] text-[#c8cad3] hover:border-[#85adff4d]"
                          }`}
                        >
                          <span className="flex items-center gap-3">
                            <span className={`inline-flex h-8 w-8 items-center justify-center rounded-md border text-xs font-bold ${
                              checked
                                ? "border-[#85adff] bg-[#85adff] text-[#002c66]"
                                : "border-[#3b4352] bg-[#0b111c] text-[#85adff]"
                            }`}>
                              {label}
                            </span>
                            <span>{option}</span>
                          </span>
                          <span className={`h-6 w-6 rounded-full border-2 ${checked ? "border-[#85adff] bg-[#85adff]" : "border-[#73757d66]"}`} />
                        </button>
                      );
                    })}
                  </div>

                  <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
                    <span className="inline-flex items-center gap-2 text-xs text-[#a9abb3]">
                      <FiFlag className="text-xs" />
                      Flag for review
                    </span>
                    <div className="flex items-center gap-2">
                      {technicalQuestionIndex > 0 && (
                        <button
                          type="button"
                          onClick={() => setTechnicalQuestionIndex((prev) => Math.max(0, prev - 1))}
                          className="rounded-xl border border-[#3d4250] bg-[#121824] px-4 py-2 text-sm font-semibold text-[#dbe3f7] transition hover:border-[#68718a]"
                        >
                          Previous
                        </button>
                      )}

                      {technicalQuestionIndex < technicalQuestions.length - 1 ? (
                        <button
                          type="button"
                          onClick={() => setTechnicalQuestionIndex((prev) => Math.min(technicalQuestions.length - 1, prev + 1))}
                          disabled={!technicalCurrentAnswered}
                          className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(90deg,#85adff,#ac8aff)] px-5 py-2.5 text-sm font-bold text-[#082b5c] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          Next Question
                          <FiArrowRight className="text-sm" />
                        </button>
                      ) : (
                        <button
                          type="button"
                          disabled={!canSubmitTechnical}
                          onClick={handleSubmitTechnical}
                          className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(90deg,#85adff,#ac8aff)] px-5 py-2.5 text-sm font-bold text-[#082b5c] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <FiSend className="text-sm" />
                          {technicalSubmitting ? "Evaluating..." : "Submit Round"}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}

              <p className="mt-5 text-center text-[10px] uppercase tracking-[0.15em] text-[#6f7584]">
                Encrypted Session • Proctored Assessment
              </p>
            </div>
          </section>
        )}

        {assessmentStage === "round1_result" && technicalEvaluation && (
          <section className={`${glassPanelClass} p-5`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-[#85adff]">Round 1 Result: Technical</p>
                <h2 className="mt-1 text-2xl font-semibold text-[#ecedf6]">
                  Correct: {technicalEvaluation.correct_count}/{technicalEvaluation.total_questions}
                </h2>
                <p className="mt-1 text-sm text-[#c8cad3]">Score: {technicalEvaluation.score_percentage}%</p>
              </div>
              <span className="inline-flex items-center gap-2 rounded-full border border-[#85adff66] bg-[#85adff12] px-3 py-1 text-xs font-semibold text-[#d6e4ff]">
                <FiCheckCircle className="text-sm" />
                Technical Evaluation Complete
              </span>
            </div>

            <div className="mt-4 rounded-2xl border border-[#45484f66] bg-[#10131a] p-3">
              <p className="text-xs uppercase tracking-[0.2em] text-[#a9abb3]">Wrong Answers Review</p>
              {technicalWrongAnswers.length === 0 ? (
                <p className="mt-2 text-sm text-emerald-300">Great work. You answered all questions correctly.</p>
              ) : (
                <div className="mt-2 space-y-3">
                  {technicalWrongAnswers.map((item) => (
                    <div key={item.question_id} className="rounded-xl border border-rose-400/40 bg-rose-500/10 p-3">
                      <p className="text-sm font-semibold text-[#ecedf6]">{item.question}</p>
                      <p className="mt-2 inline-flex items-center gap-1 text-sm text-rose-200">
                        <FiXCircle className="text-sm" />
                        Your answer: {item.selected_answer}
                      </p>
                      <p className="mt-1 text-sm text-emerald-200">Correct answer: {item.correct_answer}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="mt-4 flex justify-end">
              {!resumeQuestions.length && !resumeLoadingQuestions && !resumeEvaluation ? (
                <button
                  type="button"
                  onClick={loadResumeRound}
                  className="inline-flex items-center gap-2 rounded-full border border-[#85adff66] bg-[#85adff] px-4 py-2 text-sm font-semibold text-[#002c66] shadow-[0_10px_24px_rgba(133,173,255,0.25)] transition hover:brightness-110"
                >
                  <FiPlay className="text-sm" />
                  Next Round (Resume Skills)
                </button>
              ) : (
                <span className="inline-flex items-center gap-2 rounded-full border border-emerald-400/60 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-200">
                  <FiCheckCircle className="text-sm" />
                  Round 2 In Progress
                </span>
              )}
            </div>
          </section>
        )}

        {(assessmentStage === "round2_loading" || assessmentStage === "round2_questions") && technicalEvaluation && (
          <section className={`${glassPanelClass} mx-auto max-w-4xl p-5 md:p-7`}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-[#85adff]">Round 2: Resume Skill Assessment</p>
                <p className="mt-1 text-sm text-[#c8cad3]">Questions are generated from skills and technologies mentioned in resume.</p>
                <p className="mt-1 text-xs text-[#d9c8ff]">Detected role track: {resumeRoleTrack}</p>
              </div>
              <p className="text-sm font-medium text-[#ecedf6]">Answered: {resumeAnsweredCount}/{resumeQuestions.length || 0}</p>
            </div>

            {resumeLoadingQuestions && (
              <div className="rounded-2xl border border-[#85adff66] bg-[#85adff12] px-4 py-3 text-sm text-[#d6e4ff]">
                Loading resume round questions...
              </div>
            )}

            {!resumeLoadingQuestions && resumeQuestions.length > 0 && resumeCurrentQuestion && (
              <div className="mx-auto mt-2 max-w-3xl">
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#a9abb3]">Resume Skill Application</p>
                    <p className="mt-1 text-2xl font-semibold text-[#ecedf6]">
                      Question {resumeQuestionIndex + 1} of {resumeQuestions.length}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-xl font-bold text-[#85adff]">{getProgressPercent(resumeQuestionIndex, resumeQuestions.length)}%</p>
                    <p className="text-xs uppercase tracking-[0.16em] text-[#a9abb3]">Complete</p>
                  </div>
                </div>

                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#1b2330]">
                  <div
                    className="h-full rounded-full bg-[linear-gradient(90deg,#85adff,#ac8aff)] transition-all duration-300"
                    style={{ width: `${getProgressPercent(resumeQuestionIndex, resumeQuestions.length)}%` }}
                  />
                </div>

                <div className="mt-5 rounded-3xl border border-[#303746] bg-[rgba(14,18,27,0.92)] p-5 md:p-7">
                  <p className="text-xs uppercase tracking-[0.2em] text-[#a9abb3]">Focus: {resumeCurrentQuestion.focus || "Resume skill application"}</p>
                  <p className="mt-2 text-2xl font-semibold leading-tight text-[#ecedf6]">{resumeCurrentQuestion.question}</p>
                  <textarea
                    value={resumeAnswers[resumeQuestionIndex] || ""}
                    onChange={(event) => updateResumeAnswer(resumeQuestionIndex, event.target.value)}
                    rows={6}
                    placeholder="Write your technical answer based on your resume experience..."
                    className="mt-4 w-full resize-y rounded-xl border border-[#3a4351] bg-[#0b111c] px-4 py-3 text-sm text-[#ecedf6] outline-none transition focus:border-[#85adff]"
                  />

                  <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
                    <span className="inline-flex items-center gap-2 text-xs text-[#a9abb3]">
                      <FiFlag className="text-xs" />
                      Minimum 12 characters required
                    </span>
                    <div className="flex items-center gap-2">
                      {resumeQuestionIndex > 0 && (
                        <button
                          type="button"
                          onClick={() => setResumeQuestionIndex((prev) => Math.max(0, prev - 1))}
                          className="rounded-xl border border-[#3d4250] bg-[#121824] px-4 py-2 text-sm font-semibold text-[#dbe3f7] transition hover:border-[#68718a]"
                        >
                          Previous
                        </button>
                      )}

                      {resumeQuestionIndex < resumeQuestions.length - 1 ? (
                        <button
                          type="button"
                          onClick={() => setResumeQuestionIndex((prev) => Math.min(resumeQuestions.length - 1, prev + 1))}
                          disabled={!resumeCurrentAnswered}
                          className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(90deg,#85adff,#ac8aff)] px-5 py-2.5 text-sm font-bold text-[#082b5c] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          Next Question
                          <FiArrowRight className="text-sm" />
                        </button>
                      ) : (
                        <button
                          type="button"
                          disabled={!canSubmitResume}
                          onClick={handleSubmitResume}
                          className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(90deg,#85adff,#ac8aff)] px-5 py-2.5 text-sm font-bold text-[#082b5c] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <FiSend className="text-sm" />
                          {resumeSubmitting ? "Evaluating Round 2..." : "Submit Round"}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </section>
        )}

        {assessmentStage === "round2_result" && resumeEvaluation && (
          <section className={`${glassPanelClass} p-5`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-[#85adff]">Round 2 Result: Resume Skills</p>
                <h2 className="mt-1 text-2xl font-semibold text-[#ecedf6]">{resumeEvaluation.overall_score}% - {resumeEvaluation.verdict}</h2>
                <p className="mt-1 text-xs text-[#d9c8ff]">
                  Evaluation Engine: {resumeEvaluation.uses_llm ? "LLM + Rule Checks" : "Rule-based fallback"}
                </p>
              </div>
              <span className="inline-flex items-center gap-2 rounded-full border border-[#85adff66] bg-[#85adff12] px-3 py-1 text-xs font-semibold text-[#d6e4ff]">
                <FiCheckCircle className="text-sm" />
                Resume Evaluation Complete
              </span>
            </div>

            <div className="mt-4 space-y-3">
              {(resumeEvaluation.answer_feedback || []).map((item) => (
                <div key={item.question_id} className={`${questionCardClass} p-4`}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-[#ecedf6]">{item.question}</p>
                    <span className="rounded-full border border-[#85adff66] bg-[#85adff12] px-2 py-1 text-xs font-semibold text-[#d6e4ff]">
                      Score: {item.score}%
                    </span>
                  </div>
                  <p className="mt-2 text-xs uppercase tracking-[0.2em] text-[#a9abb3]">Your Answer</p>
                  <p className="mt-1 text-sm text-[#c8cad3]">{item.submitted_answer}</p>

                  <p className="mt-3 text-xs uppercase tracking-[0.2em] text-amber-300">Technical Feedback</p>
                  <p className="mt-1 text-sm text-[#ecedf6]">{item.feedback}</p>

                  <p className="mt-3 text-xs uppercase tracking-[0.2em] text-emerald-300">Improved Answer</p>
                  <p className="mt-1 rounded-xl border border-emerald-400/35 bg-emerald-500/10 px-3 py-2 text-sm text-slate-100">
                    {item.improved_answer}
                  </p>
                </div>
              ))}
            </div>

            {!!resumeEvaluation.final_tips?.length && (
              <div className="mt-4 rounded-2xl border border-[#45484f66] bg-[#10131a] p-3">
                <p className="text-xs uppercase tracking-[0.2em] text-[#a9abb3]">Resume Round Tips</p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-[#ecedf6]">
                  {resumeEvaluation.final_tips.map((tip) => (
                    <li key={tip}>{tip}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-4 rounded-2xl border border-emerald-400/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
              Correctness rule for this round: answers with score 70% or above are treated as correct.
            </div>

            <div className="mt-4 flex justify-end">
              {!hrQuestions.length && !hrLoadingQuestions && !hrEvaluation ? (
                <button
                  type="button"
                  onClick={loadHrRound}
                  className="inline-flex items-center gap-2 rounded-full border border-[#85adff66] bg-[#85adff] px-4 py-2 text-sm font-semibold text-[#002c66] shadow-[0_10px_24px_rgba(133,173,255,0.25)] transition hover:brightness-110"
                >
                  <FiPlay className="text-sm" />
                  Next Round (HR Interview)
                </button>
              ) : (
                <span className="inline-flex items-center gap-2 rounded-full border border-fuchsia-400/60 bg-fuchsia-500/10 px-3 py-1 text-xs font-semibold text-fuchsia-200">
                  <FiCheckCircle className="text-sm" />
                  Round 3 In Progress
                </span>
              )}
            </div>
          </section>
        )}

        {(assessmentStage === "round3_loading" || assessmentStage === "round3_questions") && resumeEvaluation && (
          <section className={`${glassPanelClass} mx-auto max-w-4xl p-5 md:p-7`}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-[#85adff]">Round 3: HR Interview</p>
                <p className="mt-1 text-sm text-[#c8cad3]">Predefined HR questions asked in real interviews.</p>
              </div>
              <p className="text-sm font-medium text-[#ecedf6]">Answered: {hrAnsweredCount}/{hrQuestions.length || 0}</p>
            </div>

            {hrLoadingQuestions && (
              <div className="rounded-2xl border border-[#85adff66] bg-[#85adff12] px-4 py-3 text-sm text-[#d6e4ff]">
                Loading predefined HR questions...
              </div>
            )}

            {!hrLoadingQuestions && hrQuestions.length > 0 && hrCurrentQuestion && (
              <div className="mx-auto mt-2 max-w-3xl">
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#a9abb3]">HR Interview Simulation</p>
                    <p className="mt-1 text-2xl font-semibold text-[#ecedf6]">
                      Question {hrQuestionIndex + 1} of {hrQuestions.length}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-xl font-bold text-[#85adff]">{getProgressPercent(hrQuestionIndex, hrQuestions.length)}%</p>
                    <p className="text-xs uppercase tracking-[0.16em] text-[#a9abb3]">Complete</p>
                  </div>
                </div>

                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#1b2330]">
                  <div
                    className="h-full rounded-full bg-[linear-gradient(90deg,#85adff,#ac8aff)] transition-all duration-300"
                    style={{ width: `${getProgressPercent(hrQuestionIndex, hrQuestions.length)}%` }}
                  />
                </div>

                <div className="mt-5 rounded-3xl border border-[#303746] bg-[rgba(14,18,27,0.92)] p-5 md:p-7">
                  <p className="text-xs uppercase tracking-[0.2em] text-[#a9abb3]">Focus: {hrCurrentQuestion.focus || "General fit"}</p>
                  <p className="mt-2 text-2xl font-semibold leading-tight text-[#ecedf6]">{hrCurrentQuestion.question}</p>
                  <textarea
                    value={hrAnswers[hrQuestionIndex] || ""}
                    onChange={(event) => updateHrAnswer(hrQuestionIndex, event.target.value)}
                    rows={6}
                    placeholder="Write your interview answer..."
                    className="mt-4 w-full resize-y rounded-xl border border-[#3a4351] bg-[#0b111c] px-4 py-3 text-sm text-[#ecedf6] outline-none transition focus:border-[#85adff]"
                  />

                  <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
                    <span className="inline-flex items-center gap-2 text-xs text-[#a9abb3]">
                      <FiFlag className="text-xs" />
                      Minimum 12 characters required
                    </span>
                    <div className="flex items-center gap-2">
                      {hrQuestionIndex > 0 && (
                        <button
                          type="button"
                          onClick={() => setHrQuestionIndex((prev) => Math.max(0, prev - 1))}
                          className="rounded-xl border border-[#3d4250] bg-[#121824] px-4 py-2 text-sm font-semibold text-[#dbe3f7] transition hover:border-[#68718a]"
                        >
                          Previous
                        </button>
                      )}

                      {hrQuestionIndex < hrQuestions.length - 1 ? (
                        <button
                          type="button"
                          onClick={() => setHrQuestionIndex((prev) => Math.min(hrQuestions.length - 1, prev + 1))}
                          disabled={!hrCurrentAnswered}
                          className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(90deg,#85adff,#ac8aff)] px-5 py-2.5 text-sm font-bold text-[#082b5c] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          Next Question
                          <FiArrowRight className="text-sm" />
                        </button>
                      ) : (
                        <button
                          type="button"
                          disabled={!canSubmitHr}
                          onClick={handleSubmitHr}
                          className="inline-flex items-center gap-2 rounded-xl bg-[linear-gradient(90deg,#85adff,#ac8aff)] px-5 py-2.5 text-sm font-bold text-[#082b5c] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <FiSend className="text-sm" />
                          {hrSubmitting ? "Evaluating Round 3..." : "Submit Round"}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </section>
        )}

        {assessmentStage === "final" && hrEvaluation && overallScore !== null && (
          <div className="grid items-start gap-5 xl:grid-cols-[2fr_1fr]">
            <section className={`${glassPanelClass} p-5`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-[#85adff]">Round 3 Result: HR Interview</p>
                  <h2 className="mt-1 text-2xl font-semibold text-[#ecedf6]">{hrEvaluation.overall_score}% - {hrEvaluation.verdict}</h2>
                  <p className="mt-1 text-xs text-[#d9c8ff]">
                    Evaluation Engine: {hrEvaluation.uses_llm ? "LLM + Rule Checks" : "Rule-based fallback"}
                  </p>
                </div>
                <span className="inline-flex items-center gap-2 rounded-full border border-[#85adff66] bg-[#85adff12] px-3 py-1 text-xs font-semibold text-[#d6e4ff]">
                  <FiCheckCircle className="text-sm" />
                  HR Evaluation Complete
                </span>
              </div>

              <div className="mt-4 space-y-3">
                {(hrEvaluation.answer_feedback || []).map((item) => (
                  <div key={item.question_id} className={`${questionCardClass} p-4`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-semibold text-[#ecedf6]">{item.question}</p>
                      <span className="rounded-full border border-[#85adff66] bg-[#85adff12] px-2 py-1 text-xs font-semibold text-[#d6e4ff]">
                        Score: {item.score}%
                      </span>
                    </div>
                    <p className="mt-2 text-xs uppercase tracking-[0.2em] text-[#a9abb3]">Your Answer</p>
                    <p className="mt-1 text-sm text-[#c8cad3]">{item.submitted_answer}</p>

                    <p className="mt-3 text-xs uppercase tracking-[0.2em] text-amber-300">Interview Feedback</p>
                    <p className="mt-1 text-sm text-[#ecedf6]">{item.feedback}</p>

                    <p className="mt-3 text-xs uppercase tracking-[0.2em] text-emerald-300">Improved Answer</p>
                    <p className="mt-1 rounded-xl border border-emerald-400/35 bg-emerald-500/10 px-3 py-2 text-sm text-slate-100">
                      {item.improved_answer}
                    </p>
                  </div>
                ))}
              </div>
            </section>

            <section className={`${glassPanelClass} p-5`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-[#85adff]">Final Overall Score</p>
                  <h2 className="mt-1 text-3xl font-semibold text-[#ecedf6]">{overallScore}%</h2>
                  <p className="mt-1 text-sm text-[#c8cad3]">Average of all three rounds.</p>
                </div>
                <span className="inline-flex items-center gap-2 rounded-full border border-[#85adff66] bg-[#85adff12] px-3 py-1 text-xs font-semibold text-[#d6e4ff]">
                  <FiCheckCircle className="text-sm" />
                  Complete
                </span>
              </div>

              <div className="mt-4 space-y-3">
                <div className="rounded-2xl border border-[#45484f66] bg-[#10131a] p-3">
                  <p className="text-xs uppercase tracking-[0.2em] text-[#a9abb3]">Technical Round</p>
                  <p className="mt-1 text-lg font-semibold text-[#ecedf6]">{technicalEvaluation?.score_percentage ?? 0}%</p>
                </div>
                <div className="rounded-2xl border border-[#45484f66] bg-[#10131a] p-3">
                  <p className="text-xs uppercase tracking-[0.2em] text-[#a9abb3]">Resume Skills Round</p>
                  <p className="mt-1 text-lg font-semibold text-[#ecedf6]">{resumeEvaluation?.overall_score ?? 0}%</p>
                </div>
                <div className="rounded-2xl border border-[#45484f66] bg-[#10131a] p-3">
                  <p className="text-xs uppercase tracking-[0.2em] text-[#a9abb3]">HR Round</p>
                  <p className="mt-1 text-lg font-semibold text-[#ecedf6]">{hrEvaluation?.overall_score ?? 0}%</p>
                </div>
              </div>
            </section>
          </div>
        )}
      </div>
    </AppShell>
  );
}

