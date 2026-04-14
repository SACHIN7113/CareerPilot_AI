import { useEffect, useMemo, useRef, useState } from "react";
import {
  FiArrowDown,
  FiArrowRight,
  FiBriefcase,
  FiCheckCircle,
  FiClock,
  FiMic,
  FiPaperclip,
  FiPlusCircle,
  FiStar,
  FiZap,
  FiUser,
  FiX,
} from "react-icons/fi";
import AppShell from "../components/layout/AppShell";
import { getQuestion, listDocuments, startPractice, submitAnswer, uploadDocument } from "../api";
import { notifyError, notifySuccess } from "../utils/toast";
import {
  patchPracticeStats,
  pushDocumentUploadHistory,
  readSelectedDocument,
} from "../utils/storage";

const HISTORY_KEY = "jarvis_chat_history_v1";

const difficultyMeta = {
  1: { label: "Easy", className: "bg-[rgba(22,163,74,0.14)] text-[#67e3b0] border-[rgba(103,227,176,0.34)]" },
  2: { label: "Medium", className: "bg-[rgba(245,158,11,0.14)] text-[#ffd48a] border-[rgba(255,212,138,0.36)]" },
  3: { label: "Hard", className: "bg-[rgba(56,189,248,0.14)] text-[#86dcff] border-[rgba(134,220,255,0.34)]" }
};

const welcomeQuickPrompts = [
  { label: "Mock Google Interview", icon: FiZap, iconClass: "text-[#8e84ff]", comingSoon: true },

];

function loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function normalizeQuestionText(rawText) {
  if (!rawText) return "";
  const withoutChunk = rawText.split("->")[0].trim();
  const firstLine = withoutChunk.split("\n").find((line) => line.trim()) || withoutChunk;
  return firstLine.trim();
}

function ensureSentence(rawText) {
  const compact = (rawText || "").replace(/\s+/g, " ").trim();
  if (!compact) return "";
  const normalized = compact.charAt(0).toUpperCase() + compact.slice(1);
  return /[.!?]$/.test(normalized) ? normalized : `${normalized}.`;
}

function answerQualityScore(text) {
  const cleaned = ensureSentence(text);
  if (!cleaned) return -10;

  const words = cleaned.split(/\s+/).filter(Boolean).length;
  let score = words;
  if (words < 6) score -= 4;
  if (/[=<>]/.test(cleaned)) score -= 2;
  if (/\b(?:etc|thing|something)\b/i.test(cleaned)) score -= 1;
  return score;
}

function buildImprovedAnswer(questionText, referenceAnswer, userAnswer) {
  const normalizedQuestion = (questionText || "").toLowerCase();
  if (normalizedQuestion.includes("swap") && normalizedQuestion.includes("python")) {
    return "In Python, you can swap two variables using tuple unpacking: a, b = b, a.";
  }

  const reference = ensureSentence(referenceAnswer);
  if (reference) return reference;

  const user = ensureSentence(userAnswer);
  if (answerQualityScore(user) >= 4) return user;
  return "";
}

function buildPracticalExtension(questionText, baseAnswer) {
  const q = (questionText || "").toLowerCase();
  const a = (baseAnswer || "").toLowerCase();

  if (q.includes("data type") && q.includes("python")) {
    return "In practice, mention grouping: int/float/bool for primitive values, str for text, and list/tuple/dict/set for collections.";
  }
  if (q.includes("numpy")) {
    return "A strong interview follow-up is that NumPy is used for fast array operations, vectorized math, and as a foundation for many ML/data libraries.";
  }
  if (q.includes("machine learning")) {
    return "For impact, add that machine learning is applied in recommendation systems, spam detection, forecasting, and computer vision tasks.";
  }
  if (q.includes("dns")) {
    return "You can strengthen this by adding that DNS translates domain names to IP addresses so browsers can connect to the correct server.";
  }
  if (q.includes("ip address")) {
    return "A practical add-on is that private IPs work inside local networks, while public IPs are used for communication over the internet.";
  }
  if (q.includes("retrieval augmented generation") || q.includes("rag")) {
    return "To make it stronger, mention the flow: retrieve relevant documents first, then generate an answer grounded in that retrieved context.";
  }

  if (a.includes(" is ") || a.includes(" are ")) {
    return "To make this interview-ready, add one real-world use case in a short second sentence.";
  }
  return "For a stronger answer, add one concise real-world example after the definition.";
}

function buildEvenBetterAnswer(questionText, referenceAnswer, improvedAnswer) {
  const normalizedQuestion = (questionText || "").toLowerCase();
  if (normalizedQuestion.includes("swap") && normalizedQuestion.includes("python")) {
    return "In Python, tuple unpacking swaps values in one step: a, b = b, a, without using a temporary variable.";
  }

  const base = ensureSentence(referenceAnswer) || ensureSentence(improvedAnswer);
  if (!base) return "";

  const extension = ensureSentence(buildPracticalExtension(questionText, base));
  if (!extension) return base;
  if (base.toLowerCase().includes(extension.toLowerCase())) return base;
  return `${base} ${extension}`;
}

function parseCoachingMessage(text) {
  const raw = (text || "").trim();
  if (!raw) return null;

  if (/^improved answer:\s*/i.test(raw)) {
    return { type: "improved", body: raw.replace(/^improved answer:\s*/i, "").trim() };
  }
  if (/^even better answer:\s*/i.test(raw)) {
    return { type: "evenBetter", body: raw.replace(/^even better answer:\s*/i, "").trim() };
  }
  if (/^next question:\s*/i.test(raw)) {
    return { type: "nextQuestion", body: raw.replace(/^next question:\s*/i, "").trim() };
  }
  if (!raw.endsWith("?")) {
    return { type: "feedback", body: raw };
  }
  return null;
}

function inferInputTypeFromTitle(title) {
  const lowered = String(title || "").toLowerCase();
  if (/\b(resume|cv|curriculum vitae|profile)\b/.test(lowered)) {
    return "resume";
  }
  return "jd";
}

export default function DashboardPage() {
  const fileInputRef = useRef(null);
  const welcomeFileInputRef = useRef(null);
  const chatScrollRef = useRef(null);
  const didLoadDocumentsRef = useRef(false);
  const nickname = localStorage.getItem("jarvis_name") || "Learner";

  const [documents, setDocuments] = useState([]);
  const [selectedDocument, setSelectedDocument] = useState(readSelectedDocument());
  const [sessionId, setSessionId] = useState("");
  const [question, setQuestion] = useState(null);
  const [answer, setAnswer] = useState("");
  const [feedback, setFeedback] = useState("");
  const [chatMessages, setChatMessages] = useState([]);
  const [awaitingConfirmation, setAwaitingConfirmation] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [difficulty, setDifficulty] = useState(1);
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [pendingNextQuestion, setPendingNextQuestion] = useState(false);
  const [assistantStatus, setAssistantStatus] = useState("");
  const [typingFrame, setTypingFrame] = useState(0);

  const [historyItems, setHistoryItems] = useState(loadHistory());
  const [activeHistoryId, setActiveHistoryId] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [welcomePrompt, setWelcomePrompt] = useState("");
  const [welcomeAttachment, setWelcomeAttachment] = useState(null);
  const [pendingChatAttachment, setPendingChatAttachment] = useState(null);

  useEffect(() => {
    if (didLoadDocumentsRef.current) return;
    didLoadDocumentsRef.current = true;
    refreshDocuments();
  }, []);

  useEffect(() => {
    chatScrollRef.current?.scrollTo({ top: chatScrollRef.current.scrollHeight, behavior: "smooth" });
  }, [chatMessages, assistantStatus, typingFrame]);

  useEffect(() => {
    if (!assistantStatus) {
      setTypingFrame(0);
      return;
    }
    const timer = setInterval(() => {
      setTypingFrame((prev) => (prev + 1) % 3);
    }, 350);
    return () => clearInterval(timer);
  }, [assistantStatus]);

  useEffect(() => {
    if (error) {
      notifyError(error);
    }
  }, [error]);

  useEffect(() => {
    if (!activeHistoryId) return;
    setHistoryItems((prev) => {
      const next = prev.map((item) =>
        item.id === activeHistoryId
          ? {
              ...item,
              updatedAt: Date.now(),
              chatMessages,
              selectedDocument,
              sessionId,
              question,
              feedback,
              difficulty,
              awaitingConfirmation
            }
          : item
      );
      localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
      return next;
    });
  }, [
    activeHistoryId,
    chatMessages,
    selectedDocument,
    sessionId,
    question,
    feedback,
    difficulty,
    awaitingConfirmation
  ]);

  function pushMessage(role, text, options = {}) {
    setChatMessages((prev) => [...prev, { id: crypto.randomUUID(), role, text, createdAt: Date.now(), ...options }]);
  }

  function pushAssistant(text) {
    pushMessage("assistant", text);
  }

  function pushUser(text, options = {}) {
    pushMessage("user", text, options);
  }

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function pushAssistantMessagesSequential(messages) {
    const queue = messages.filter(Boolean);
    for (let i = 0; i < queue.length; i += 1) {
      setAssistantStatus("typing");
      await wait(i === 0 ? 380 : 260);
      pushAssistant(queue[i]);
      setAssistantStatus("");
      if (i < queue.length - 1) {
        await wait(220);
      }
    }
  }

  async function fetchNextQuestionWithRetry(activeSessionId, retries = 2) {
    let lastError;
    for (let i = 0; i <= retries; i += 1) {
      try {
        return await getQuestion(activeSessionId);
      } catch (err) {
        lastError = err;
        const status = Number(err?.status || 0);
        if (status >= 400 && status < 500) {
          throw err;
        }
        if (i < retries) {
          await new Promise((resolve) => setTimeout(resolve, 500));
        }
      }
    }
    throw lastError;
  }

  function createHistoryItem(title, initialMessages, documentId) {
    const item = {
      id: crypto.randomUUID(),
      title,
      updatedAt: Date.now(),
      chatMessages: initialMessages,
      selectedDocument: documentId,
      sessionId: "",
      question: null,
      feedback: "",
      difficulty: 1,
      awaitingConfirmation: false
    };
    setHistoryItems((prev) => {
      const next = [item, ...prev].slice(0, 30);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
      return next;
    });
    setActiveHistoryId(item.id);
  }

  function openHistory(item) {
    setIsChatOpen(true);
    setActiveHistoryId(item.id);
    setChatMessages(item.chatMessages || []);
    setPendingChatAttachment(null);
    setWelcomeAttachment(null);
    setSelectedDocument(item.selectedDocument || "");
    setSessionId(item.sessionId || "");
    setQuestion(item.question || null);
    setFeedback(item.feedback || "");
    setDifficulty(item.difficulty || 1);
    setAwaitingConfirmation(Boolean(item.awaitingConfirmation));
    setError("");
  }

  async function refreshDocuments() {
    try {
      const payload = await listDocuments({ withOverview: false });
      setDocuments(payload);
      if (!selectedDocument && payload.length) {
        const nextId = payload[0].id;
        setSelectedDocument(nextId);
      }
    } catch (err) {
      setError(err.message);
    }
  }

  async function uploadAttachment(file, setAttachment) {
    if (!file) return null;

    setError("");
    setAttachment({ file, uploadedDocument: null, isUploading: true, error: "" });
    try {
      const uploaded = await uploadDocument(file);
      await refreshDocuments();
      setSelectedDocument(uploaded.id);
      pushDocumentUploadHistory(uploaded, "dashboard");
      setAttachment({ file, uploadedDocument: uploaded, isUploading: false, error: "" });
      notifySuccess("JD uploaded successfully.");
      patchPracticeStats((stats) => ({
        ...stats,
        documentsUploaded: stats.documentsUploaded + 1,
        lastDocumentTitle: uploaded.title || file.name
      }));
      return uploaded;
    } catch (err) {
      setError(err.message);
      setAttachment({ file, uploadedDocument: null, isUploading: false, error: err.message });
      return null;
    }
  }

  async function startChatFromAttachment(attachment, promptText = "") {
    const uploaded = attachment?.uploadedDocument;
    const attachmentName = uploaded?.title || attachment?.file?.name || "JD";
    if (!uploaded) {
      throw new Error(attachment?.error || "JD is not ready yet.");
    }

    setSelectedDocument(uploaded.id);
    setSessionId("");
    setQuestion(null);
    setFeedback("");
    setAwaitingConfirmation(false);
    setPendingChatAttachment(null);
    setWelcomeAttachment(null);

    const initial = [
      {
        id: crypto.randomUUID(),
        role: "user",
        text: promptText.trim(),
        attachmentName,
        createdAt: Date.now(),
      },
      {
        id: crypto.randomUUID(),
        role: "assistant",
        text: `Hey ${nickname}, I received "${attachmentName}". I am starting with an easy question.`,
        createdAt: Date.now(),
      },
    ];

    const firstQuestion = await startFirstQuestion(uploaded.id, attachmentName, { announce: false });
    const bootMessages = [
      ...initial,
      {
        id: crypto.randomUUID(),
        role: "assistant",
        text: firstQuestion,
        createdAt: Date.now(),
      },
    ];

    setChatMessages(bootMessages);
    setIsChatOpen(true);
    createHistoryItem(attachmentName || "New chat", bootMessages, uploaded.id);

    setAnswer("");
    setWelcomePrompt("");
  }

  async function handleUpload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    await uploadAttachment(file, setPendingChatAttachment);
    event.target.value = "";
  }

  async function handleWelcomeSend() {
    if (!welcomeAttachment) {
      setError("Attach a JD before sending.");
      return;
    }
    if (welcomeAttachment.isUploading) {
      setError("JD is still uploading. Please wait a moment.");
      return;
    }

    setLoading(true);
    setError("");
    try {
      await startChatFromAttachment(welcomeAttachment, welcomePrompt.trim());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function startFirstQuestion(documentId = selectedDocument, documentTitle = "", options = {}) {
    const announce = options.announce !== false;
    const resolvedTitle = documentTitle || documents.find((doc) => doc.id === documentId)?.title || "this JD";
    const inputType = inferInputTypeFromTitle(resolvedTitle);
    const session = await startPractice(documentId, { inputType });
    const nextQuestion = await fetchNextQuestionWithRetry(session.session_id);

    const normalizedQuestion = normalizeQuestionText(nextQuestion.question_text);
    setSessionId(session.session_id);
    setQuestion({ ...nextQuestion, question_text: normalizedQuestion });
    setDifficulty(session.difficulty);
    setPendingNextQuestion(false);
    setAwaitingConfirmation(false);
    // pushAssistant(`Starting with an ${difficultyMeta[session.difficulty]?.label.toLowerCase() || "easy"} question from "${resolvedTitle}".`);
    if (announce) {
      pushAssistant(normalizedQuestion);
    }
    setAnswer("");

    patchPracticeStats((stats) => ({
      ...stats,
      sessionsStarted: stats.sessionsStarted + 1,
      lastDifficulty: session.difficulty,
      lastDocumentTitle: resolvedTitle || stats.lastDocumentTitle
    }));

    return normalizedQuestion;
  }

  async function handlePrimaryAction() {
    if (pendingChatAttachment) {
      if (pendingChatAttachment.isUploading) {
        setError("JD is still uploading. Please wait a moment.");
        return;
      }

      setAssistantStatus("Preparing your practice session");
      setLoading(true);
      setError("");
      try {
        await startChatFromAttachment(pendingChatAttachment, answer.trim());
      } catch (err) {
        setError(err.message);
      } finally {
        setAssistantStatus("");
        setLoading(false);
      }
      return;
    }

    if (!selectedDocument) {
      setError("Upload or choose a JD first.");
      return;
    }

    if (awaitingConfirmation || !question) {
      setAssistantStatus("Generating your first question");
      setLoading(true);
      setError("");
      setFeedback("");
      try {
        await startFirstQuestion();
      } catch (err) {
        setError(err.message);
        pushAssistant("I could not start practice right now. Please try again.");
      } finally {
        setAssistantStatus("");
        setLoading(false);
      }
      return;
    }

    if (pendingNextQuestion) {
      setAnswer("");
      setAssistantStatus("Preparing your next question");
      setLoading(true);
      setError("");
      try {
        const nextQuestion = await fetchNextQuestionWithRetry(sessionId);
        const normalizedQuestion = normalizeQuestionText(nextQuestion.question_text);
        setQuestion({ ...nextQuestion, question_text: normalizedQuestion });
        setPendingNextQuestion(false);
        pushAssistant(`Next question: ${normalizedQuestion}`);
      } catch (err) {
        setError(err.message);
        pushAssistant("I still could not load the next question. Please try again in a moment.");
      } finally {
        setAssistantStatus("");
        setLoading(false);
      }
      return;
    }

    if (!answer.trim()) {
      setError("Type your answer before sending.");
      return;
    }

    const userAnswer = answer.trim();
    setAnswer("");
    setAssistantStatus("Evaluating your answer");
    setLoading(true);
    setError("");
    try {
      pushUser(userAnswer);
      const result = await submitAnswer(sessionId, question.question_id, userAnswer);
      setAssistantStatus("Preparing your next question");
      let nextQuestion = null;
      let normalizedQuestion = "";
      try {
        nextQuestion = await fetchNextQuestionWithRetry(sessionId);
        normalizedQuestion = normalizeQuestionText(nextQuestion.question_text);
      } catch {
        setPendingNextQuestion(true);
      }

      setFeedback(result.feedback);
      setDifficulty(result.updated_difficulty);
      if (nextQuestion) {
        setQuestion({ ...nextQuestion, question_text: normalizedQuestion });
      } else {
        setQuestion(null);
      }

      const assistantReplies = [`Coaching feedback: ${result.feedback}`];
      const improvedAnswer = buildImprovedAnswer(question?.question_text, result.reference_answer, userAnswer);
      if (improvedAnswer) {
        assistantReplies.push(`Improved answer: ${improvedAnswer}`);
      }
      const evenBetterAnswer = buildEvenBetterAnswer(question?.question_text, result.reference_answer, improvedAnswer);
      if (evenBetterAnswer && evenBetterAnswer !== improvedAnswer) {
        assistantReplies.push(`Even better answer: ${evenBetterAnswer}`);
      }
      if (nextQuestion) {
        assistantReplies.push(`Next question: ${normalizedQuestion}`);
      } else {
        assistantReplies.push("I checked your answer, but the next question is taking too long. Type anything and send to retry.");
      }

      setAssistantStatus("");
      await pushAssistantMessagesSequential(assistantReplies);

      patchPracticeStats((stats) => ({
        ...stats,
        questionsAnswered: stats.questionsAnswered + 1,
        lastDifficulty: result.updated_difficulty,
        lastFeedback: result.feedback
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setAssistantStatus("");
      setLoading(false);
    }
  }

  function handleComposerKeyDown(event) {
    if (event.key !== "Enter") return;
    if (event.shiftKey) return;
    event.preventDefault();
    if (!loading) {
      handlePrimaryAction();
    }
  }

  function handleWelcomeKeyDown(event) {
    if (event.key !== "Enter") return;
    if (event.shiftKey) return;
    event.preventDefault();
    if (!loading && welcomeAttachment) {
      handleWelcomeSend();
    }
  }

  const selectedTitle = useMemo(
    () => documents.find((doc) => doc.id === selectedDocument)?.title || "No JD selected",
    [documents, selectedDocument]
  );

  const answeredCount = useMemo(
    () => chatMessages.filter((message) => message.role === "user" && message.text?.trim()).length,
    [chatMessages]
  );

  const liveConfidence = useMemo(() => {
    const positiveSignal = /(strong|great|excellent|clear|accurate|confident)/i.test(feedback || "");
    const negativeSignal = /(weak|unclear|incorrect|missing|improve)/i.test(feedback || "");
    let score = 84 + answeredCount * 2;
    if (positiveSignal) score += 2;
    if (negativeSignal) score -= 3;
    return Math.max(78, Math.min(92, score));
  }, [answeredCount, feedback]);

  const confidenceLabel = useMemo(() => {
    if (liveConfidence >= 88) return "HIGH";
    if (liveConfidence >= 75) return "STRONG";
    return "GROWING";
  }, [liveConfidence]);

  const performanceDelta = useMemo(() => {
    const base = Math.round((liveConfidence - 80) / 2) + Math.min(answeredCount, 4);
    return Math.max(1, Math.min(9, base));
  }, [liveConfidence, answeredCount]);

  const traitMetrics = useMemo(() => {
    const confidence = Math.max(62, Math.min(95, liveConfidence + 2));
    const technicalDepth = Math.max(55, Math.min(92, 58 + answeredCount * 5));
    const conciseBias = answer.trim().length > 280 ? -8 : 4;
    const conciseness = Math.max(30, Math.min(80, 52 + conciseBias));

    return [
      {
        name: "Confidence",
        value: confidence,
        level: confidence >= 82 ? "High" : "Steady",
        levelClass: "text-[#b9aaff]",
        barClass: "from-[#bca8ff] to-[#8b69ff]"
      },
      {
        name: "Technical Depth",
        value: technicalDepth,
        level: technicalDepth >= 76 ? "Optimal" : "Growing",
        levelClass: "text-[#4fd1ff]",
        barClass: "from-[#67deff] to-[#2ca8ff]"
      },
      {
        name: "Conciseness",
        value: conciseness,
        level: conciseness <= 50 ? "Low" : "Good",
        levelClass: conciseness <= 50 ? "text-[#ff6d8d]" : "text-[#f4a3b8]",
        barClass: conciseness <= 50 ? "from-[#ff7f98] to-[#ff5f84]" : "from-[#f2aac0] to-[#e087ab]"
      }
    ];
  }, [liveConfidence, answeredCount, answer]);

  const sessionInsights = useMemo(() => {
    const insights = [];
    if (/great|strong|excellent|clear|accurate/i.test(feedback || "")) {
      insights.push("Excellent articulation in your last response.");
    } else {
      insights.push("Strong structure in your answer; keep each point concise.");
    }
    insights.push("Mention one trade-off and one fallback strategy to sound senior.");
    if (question?.question_text) {
      insights.push(`Prepare one concrete example for: ${question.question_text.slice(0, 52)}...`);
    }
    return insights.slice(0, 3);
  }, [feedback, question]);

  const firstAssistantMessageId = useMemo(
    () => chatMessages.find((message) => message.role === "assistant")?.id || "",
    [chatMessages]
  );

  function formatMessageTime(timestamp) {
    if (!timestamp) return "";
    try {
      return new Date(timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    } catch {
      return "";
    }
  }

  function clearChatHistory() {
    setHistoryItems([]);
    localStorage.removeItem(HISTORY_KEY);
    setActiveHistoryId("");
  }

  async function handleStartNewSession() {
    setIsChatOpen(false);
    setHistoryOpen(false);
    setPendingChatAttachment(null);
    setWelcomeAttachment(null);
    setWelcomePrompt("");
    setChatMessages([]);
    setActiveHistoryId("");
    setSelectedDocument("");
    setSessionId("");
    setQuestion(null);
    setAnswer("");
    setFeedback("");
    setDifficulty(1);
    setPendingNextQuestion(false);
    setAwaitingConfirmation(false);
    setAssistantStatus("");
    setError("");
    setLoading(false);
  }

  return (
    <AppShell
      title={isChatOpen ? "CareerPilot AI" : "AI Prepare Assistant"}
      subtitle={isChatOpen ? "" : "One focused workspace for questions, uploads, and live practice."}
      fullBleed
      onStartNewSession={handleStartNewSession}
      headerActions={
        <button
          type="button"
          onClick={() => setHistoryOpen((v) => !v)}
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium transition ${
            historyOpen
              ? "border-[rgba(167,165,255,0.38)] bg-[rgba(100,94,251,0.24)] text-[#d7d5ff]"
              : "border-[rgba(167,165,255,0.22)] bg-[rgba(38,38,38,0.62)] text-slate-300 hover:border-[rgba(167,165,255,0.36)] hover:text-slate-100"
          }`}
          title={historyOpen ? "Close history" : "Open history"}
        >
          {historyOpen ? <FiX className="text-sm" /> : <FiClock className="text-sm" />}
          <span>History</span>
        </button>
      }
    >
      <div className={`flex min-h-0 flex-1 ${isChatOpen ? "gap-2" : "gap-4"}`}>
        <div className="min-w-0 flex min-h-0 flex-1">
          {!isChatOpen ? (
            <section className="flex flex-1 items-start overflow-y-auto bg-transparent px-3 pb-8 pt-4 sm:px-2">
              <div className="mx-auto w-full max-w-6xl space-y-7">
                <div className="max-w-3xl">
                  <p className="text-xs font-semibold uppercase tracking-[0.25em] text-indigo-300/90 sm:text-sm">AI Prepare</p>
                  <h1 className="mt-3 text-4xl font-semibold leading-[1.08] text-indigo-200 sm:text-5xl lg:text-6xl">Hey {nickname}, ready to practice?</h1>
                  <p className="mt-4 max-w-2xl text-base leading-7 text-slate-300 sm:text-lg">
                    Upload your JD to generate an interview-style question flow tailored to the exact role requirements.
                  </p>
                </div>

                <section className="group relative max-w-4xl overflow-hidden rounded-3xl bg-[linear-gradient(112deg,#1a1d27_0%,#1d1d24_54%,#2a2b3a_100%)] p-5 shadow-[0_26px_60px_rgba(2,8,24,0.32)] transition duration-500 hover:bg-[linear-gradient(112deg,#22263a_0%,#222333_52%,#353756_100%)] sm:p-6">
                  <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_78%_34%,rgba(147,120,255,0.18),transparent_60%)] opacity-30 transition duration-500 group-hover:opacity-85" />

                  <div className="relative z-10">
                    <div className="inline-flex h-11 w-11 items-center justify-center rounded-2xl border border-[#7e6cff]/30 bg-[#7e6cff]/20 text-[#9f90ff]">
                      {welcomeAttachment?.uploadedDocument ? <FiCheckCircle className="text-lg" /> : <FiPaperclip className="text-lg" />}
                    </div>
                    <h2 className="mt-3 text-[36px] font-semibold leading-[1.1] text-white sm:mt-4 sm:text-[40px]">Contextual Intelligence</h2>
                    <p className="mt-2 text-base leading-7 text-slate-300">
                      Drop your Job Description here. We analyze role expectations and targeted technical and behavioral requirements.
                    </p>

                    <input
                      ref={welcomeFileInputRef}
                      type="file"
                      accept=".txt,.pdf,.docx"
                      onChange={async (event) => {
                        const picked = event.target.files?.[0] || null;
                        if (picked) {
                          await uploadAttachment(picked, setWelcomeAttachment);
                        } else {
                          setWelcomeAttachment(null);
                        }
                        event.target.value = "";
                      }}
                      className="hidden"
                    />

                    <button
                      type="button"
                      onClick={() => welcomeFileInputRef.current?.click()}
                      className="mt-5 flex w-full flex-col items-center justify-center rounded-[40px] border border-dashed border-[#7b73b8]/80 bg-[#06080f]/95 px-5 py-6 text-center transition duration-300 hover:border-[#9487ff] sm:py-7"
                    >
                      <FiPlusCircle className="mb-2 text-xl text-slate-500" />
                      <span className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-300">
                        {welcomeAttachment?.file?.name || "Select Files Or Drag Here"}
                      </span>
                    </button>

                    <p className="mt-3 text-sm text-slate-400">
                      {welcomeAttachment
                        ? welcomeAttachment.isUploading
                          ? "Uploading JD..."
                          : welcomeAttachment.uploadedDocument
                          ? "JD uploaded and ready."
                          : "JD upload failed. Please retry."
                        : "Supported formats: PDF, DOCX, TXT"}
                    </p>
                  </div>
                </section>

                <section className="max-w-5xl">
                  <div className="group relative overflow-hidden rounded-full border border-[#30344b] bg-[#040712] px-4 py-2 shadow-[0_20px_58px_rgba(7,14,42,0.6),inset_0_1px_0_rgba(255,255,255,0.05)] transition duration-500 hover:border-[#4b4f73]">
                    <div className="pointer-events-none absolute inset-0 rounded-full bg-[radial-gradient(circle_at_84%_50%,rgba(116,103,248,0.24),transparent_58%)] opacity-70" />

                    <div className="relative z-10 flex items-center gap-2.5">
                      <button
                        type="button"
                        onClick={() => welcomeFileInputRef.current?.click()}
                        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border border-[#2f3550] bg-[#0c1223] text-slate-400 transition hover:text-slate-200"
                        title="Attach JD"
                      >
                        <FiPaperclip className="text-sm" />
                      </button>

                      <span className="h-7 w-px bg-[#343954]" />

                      <textarea
                        value={welcomePrompt}
                        onChange={(event) => setWelcomePrompt(event.target.value)}
                        onKeyDown={handleWelcomeKeyDown}
                        rows={1}
                        placeholder="Ask CareerPilot AI/ anything or type '/' for commands..."
                        className="h-10 min-h-[40px] max-h-[40px] flex-1 resize-none bg-transparent px-1 py-2 text-sm text-slate-200 outline-none placeholder:text-slate-500"
                      />

                      <span className="hidden text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500 sm:inline">⌘ + Enter</span>

                      <button
                        type="button"
                        disabled={loading || !welcomeAttachment || welcomeAttachment.isUploading}
                        onClick={handleWelcomeSend}
                        className="inline-flex h-10 flex-shrink-0 items-center justify-center rounded-full border border-[#5d59a7] bg-[linear-gradient(135deg,#9e96ff,#7e70ff)] px-7 text-sm font-semibold text-white shadow-[0_10px_24px_rgba(121,109,255,0.4)] transition hover:brightness-110 disabled:border-[#3f4563] disabled:bg-[#222741] disabled:text-slate-300 disabled:shadow-none disabled:cursor-not-allowed"
                        title="Ask AI"
                      >
                        Ask AI
                      </button>
                    </div>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2.5">
                    {welcomeQuickPrompts.map((chip) => (
                      <button
                        key={chip.label}
                        type="button"
                        onClick={() => {
                          if (chip.comingSoon) {
                            notifySuccess("This feature is coming soon.");
                            return;
                          }
                          setWelcomePrompt(chip.label);
                        }}
                        className="inline-flex items-center gap-2 rounded-full border border-[#3a3f58] bg-[linear-gradient(180deg,#232834_0%,#1d2230_100%)] px-4 py-2 text-sm font-medium text-slate-300 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] transition hover:border-[#6d6fd4] hover:text-slate-100"
                      >
                        <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-[#2c3244]">
                          <chip.icon className={`text-[10px] ${chip.iconClass}`} />
                        </span>
                        {chip.label}
                      </button>
                    ))}
                  </div>
                </section>
              </div>
            </section>
          ) : (
            /* Chat workspace */
            <section className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-[32px] bg-[radial-gradient(circle_at_13%_80%,rgba(80,120,255,0.1),transparent_36%),radial-gradient(circle_at_68%_4%,rgba(93,84,255,0.11),transparent_34%),linear-gradient(180deg,#090909_0%,#101018_56%,#0d0f1b_100%)]">
              <div className="flex items-center justify-between px-6 py-4">
                <div>
                  <p className="ui-label text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500"></p>
                  <p className="mt-1 text-sm font-medium text-slate-200">{selectedTitle}</p>
                </div>
                <div>
                  <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${difficultyMeta[difficulty]?.className || difficultyMeta[1].className}`}>
                    {difficultyMeta[difficulty]?.label || "Easy"}
                  </span>
                </div>
              </div>

              <div
                ref={chatScrollRef}
                className="min-h-0 flex-1 space-y-5 overflow-y-auto bg-[radial-gradient(circle_at_12%_84%,rgba(89,120,255,0.07),transparent_40%),radial-gradient(circle_at_83%_90%,rgba(43,98,255,0.05),transparent_50%)] px-7 py-6"
              >
                {chatMessages.map((message, index) => {
                  const isUser = message.role === "user";
                  const coaching = !isUser && message.text ? parseCoachingMessage(message.text) : null;

                  if (coaching?.type === "evenBetter") {
                    return null;
                  }

                  return (
                    <div key={message.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                      {!isUser && (
                        <div className="mr-3 mt-8 hidden h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[radial-gradient(circle_at_30%_30%,#b8b1ff_0%,#7b6fff_62%,#655ad6_100%)] shadow-[0_0_18px_rgba(130,110,255,0.62)] sm:flex">
                          <FiBriefcase className="text-[10px] text-white" />
                        </div>
                      )}

                      <div className={isUser ? "max-w-[60%]" : "max-w-[74%]"}>
                        {isUser ? (
                          <div className="mb-2 flex items-center justify-end gap-1.5 ui-label text-[11px] font-semibold uppercase tracking-[0.12em] text-[#8f95b0]">
                            <span>YOU</span>
                            {formatMessageTime(message.createdAt) && <span>• {formatMessageTime(message.createdAt)}</span>}
                            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-[rgba(63,68,88,0.7)] text-[#a9afcc]">
                              <FiUser className="text-[11px]" />
                            </span>
                          </div>
                        ) : (
                          <p className="mb-2 ui-label text-[11px] font-semibold uppercase tracking-[0.24em] text-[#7f89a8]">JARVIS • AI MENTOR</p>
                        )}

                        <div
                          className={`rounded-[26px] px-5 py-4 text-sm leading-[1.6] transition-all duration-200 ${
                            isUser
                              ? "border border-[rgba(167,165,255,0.28)] bg-[linear-gradient(124deg,#2f3354_0%,#2c2f4f_54%,#2a2e4b_100%)] text-[#e4e6f5] shadow-[0_24px_48px_rgba(0,0,0,0.4),0_0_28px_rgba(100,94,251,0.06)] hover:bg-[linear-gradient(124deg,#34385f_0%,#313659_54%,#2e3455_100%)]"
                              : "border border-[rgba(167,165,255,0.2)] bg-[linear-gradient(132deg,#1f2028_0%,#1b1c24_62%,#191b22_100%)] text-[#d7d9e1] shadow-[0_24px_48px_rgba(0,0,0,0.4),0_0_28px_rgba(100,94,251,0.05)] hover:bg-[linear-gradient(132deg,#242530_0%,#20222d_62%,#1d1f29_100%)]"
                          }`}
                        >
                          {message.attachmentName && (
                            <div className="mb-3 inline-flex max-w-full items-center rounded-full border border-[rgba(167,165,255,0.24)] bg-[rgba(53,56,82,0.62)] px-3 py-1 text-xs font-medium text-[#ccd1ee]">
                              <span className="truncate">{message.attachmentName}</span>
                            </div>
                          )}

                          {message.text ? (
                            !isUser && coaching ? (
                              coaching.type === "feedback" ? (
                                <p className="text-base leading-7 text-[#d7d9e1]">{coaching.body.replace(/^coaching feedback:\s*/i, "").trim()}</p>
                              ) : coaching.type === "improved" ? (
                                <article className="rounded-[22px] bg-[linear-gradient(132deg,#1f2028_0%,#1b1c24_62%,#191b22_100%)] px-4 py-4 shadow-[0_20px_40px_rgba(0,0,0,0.32)]">
                                  <p className="ui-label mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-emerald-300">
                                    <FiCheckCircle className="text-sm" />
                                    <span>Improved Answer</span>
                                  </p>
                                  <p className="text-[15px] leading-7 text-[#d6f6e9]">{coaching.body}</p>
                                </article>
                              ) : coaching.type === "nextQuestion" ? (
                                <article className="rounded-[18px] bg-[rgba(44,69,98,0.4)] px-4 py-3">
                                  <p className="ui-label mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-sky-300">Next Question</p>
                                  <p className="text-[#d8e7ff]">{coaching.body}</p>
                                </article>
                              ) : (
                                <p>{message.text}</p>
                              )
                            ) : (
                              <p>{message.text}</p>
                            )
                          ) : null}

                          {!isUser && message.id === firstAssistantMessageId && index < 3 && (
                            <p className="mt-2.5 text-[10px] text-slate-400">This is the first message from CareerPilot.</p>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}

                {assistantStatus && (
                  <div className="flex justify-start">
                    <div className="mr-2.5 mt-2 hidden h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[radial-gradient(circle_at_30%_30%,#b8b1ff_0%,#7b6fff_62%,#655ad6_100%)] shadow-[0_0_18px_rgba(130,110,255,0.62)] sm:flex">
                      <FiBriefcase className="text-[10px] text-white" />
                    </div>
                    <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(29,31,43,0.9)] px-4 py-2 shadow-[0_16px_36px_rgba(0,0,0,0.35)]" aria-live="polite" aria-label="CareerPilot is typing">
                      {[0, 1, 2].map((dot) => (
                        <span
                          key={dot}
                          className={`h-1.5 w-1.5 rounded-full bg-indigo-300 transition-opacity duration-200 ${typingFrame === dot ? "opacity-100" : "opacity-35"}`}
                        />
                      ))}
                      <span className="text-xs text-slate-400">CareerPilot is analyzing...</span>
                    </div>
                  </div>
                )}
              </div>

              <div className="sticky bottom-0 bg-[linear-gradient(180deg,rgba(10,14,24,0)_0%,rgba(10,14,24,0.82)_28%,rgba(10,14,24,0.98)_100%)] px-6 py-4 backdrop-blur">
                <div className="flex items-center gap-2 rounded-[22px] bg-[#050607] px-3 py-2 shadow-[0_18px_34px_rgba(0,0,0,0.45)]">
                  <input ref={fileInputRef} type="file" accept=".txt,.pdf,.docx" onChange={handleUpload} className="hidden" />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-[#1f1f24] text-slate-300 transition hover:bg-[#2a2a32] hover:text-slate-100"
                    title="Upload JD"
                  >
                    <FiPaperclip className="text-sm" />
                  </button>

                  <textarea
                    value={answer}
                    onChange={(event) => setAnswer(event.target.value)}
                    onKeyDown={handleComposerKeyDown}
                    rows={1}
                    placeholder={
                      awaitingConfirmation
                        ? "Press send to start practice"
                        : pendingNextQuestion
                        ? "Type and send to retry loading next question..."
                        : pendingChatAttachment?.isUploading
                        ? "JD is uploading in the background..."
                        : question
                        ? "Explain your architectural choices..."
                        : selectedDocument
                        ? "Press send to start practice"
                        : "Upload JD first"
                    }
                    className="h-10 min-h-[40px] max-h-[40px] flex-1 resize-none bg-transparent px-2 py-2 text-sm text-[#d8dae4] outline-none placeholder:text-[rgba(215,217,225,0.45)]"
                  />

                  <button
                    type="button"
                    className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-[#1f1f24] text-slate-300"
                    title="Voice input"
                  >
                    <FiMic className="text-sm" />
                  </button>

                  <button
                    type="button"
                    disabled={loading}
                    onClick={handlePrimaryAction}
                    className="inline-flex h-11 items-center gap-2 rounded-full bg-[linear-gradient(135deg,#a7a5ff,#645efb)] px-6 text-sm font-semibold text-white shadow-[0_14px_28px_rgba(100,94,251,0.38)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                    aria-label={awaitingConfirmation ? "Start practice" : question ? "Submit answer" : "Start practice"}
                    title={awaitingConfirmation ? "Start practice" : question ? "Submit answer" : "Start practice"}
                  >
                    <span>Send</span>
                    <FiArrowRight className="text-sm" />
                  </button>
                </div>

                  {pendingChatAttachment && (
                    <div className="mt-3 flex max-w-full items-center justify-between gap-2 rounded-2xl border border-[#334061]/70 bg-[#151f39]/80 px-3 py-2 text-sm text-slate-200">
                      <div className="min-w-0">
                        <p className="truncate font-medium">{pendingChatAttachment.file.name}</p>
                        <p className="text-xs text-slate-400">
                          {pendingChatAttachment.isUploading
                            ? "Uploading JD in the background..."
                            : pendingChatAttachment.uploadedDocument
                            ? "JD uploaded. Press send to start chat fast."
                            : "Upload failed"}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setPendingChatAttachment(null)}
                        className="flex h-7 w-7 items-center justify-center rounded-full border border-slate-500/70 text-slate-400 transition hover:text-slate-100"
                      >
                        <FiX className="text-sm" />
                      </button>
                    </div>
                  )}

                <p className="mt-2 text-center text-[11px] text-slate-500">Press <span className="rounded-full bg-[#2a2b2f] px-2 py-[1px] text-[10px] text-slate-300">Enter</span> to submit your response</p>
              </div>
            </section>
          )}
        </div>

        {isChatOpen ? (
          historyOpen ? (
            <aside className="hidden min-h-0 w-[320px] flex-shrink-0 lg:block">
              <div className="flex h-full min-h-0 flex-col rounded-3xl border border-slate-800 bg-[#08112e]">
                <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
                  <div>
                    <p className="text-base font-semibold text-slate-100">Chat History</p>
                    <p className="text-xs text-slate-400">All uploaded document sessions</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {!!historyItems.length && (
                      <button
                        type="button"
                        onClick={clearChatHistory}
                        className="rounded-full border border-red-400/40 bg-red-500/10 px-3 py-1 text-xs font-medium text-red-300 transition hover:bg-red-500/20"
                      >
                        Clear
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setHistoryOpen(false)}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-slate-700 text-slate-300 transition hover:text-slate-100"
                      title="Close history"
                    >
                      <FiX className="text-sm" />
                    </button>
                  </div>
                </div>

                <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
                  {historyItems.length ? (
                    historyItems.map((item) => {
                      const messageCount = Array.isArray(item.chatMessages) ? item.chatMessages.length : 0;
                      const isActive = item.id === activeHistoryId;
                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => {
                            openHistory(item);
                            setHistoryOpen(false);
                          }}
                          className={`w-full rounded-2xl border px-3 py-2 text-left transition ${
                            isActive
                              ? "border-indigo-400/50 bg-indigo-500/15"
                              : "border-slate-700 bg-[#0d173a] hover:border-indigo-400/40"
                          }`}
                        >
                          <p className="truncate text-sm font-semibold text-slate-100">{item.title}</p>
                          <p className="mt-1 text-[11px] uppercase tracking-[0.08em] text-slate-400">
                            {new Date(item.updatedAt).toLocaleString()}
                          </p>
                          <p className="mt-1 text-xs text-slate-300">{messageCount} messages</p>
                        </button>
                      );
                    })
                  ) : (
                    <div className="rounded-2xl border border-slate-700 bg-[#0d173a] p-4 text-sm text-slate-400">
                      No chat history yet. Start a session by uploading a JD and sending your first prompt.
                    </div>
                  )}
                </div>
              </div>
            </aside>
          ) : (
            <aside className="hidden min-h-0 w-[314px] flex-shrink-0 lg:block">
              <div className="flex h-full min-h-0 flex-col bg-[linear-gradient(180deg,rgba(19,19,19,0.66)_0%,rgba(19,19,19,0.35)_100%)] pl-5 pr-2">
                <div>
                  <p className="text-base font-semibold text-slate-100">Live Performance Hub</p>
                  <p className="mt-1 text-xs text-slate-500">Real-time analysis of your responses</p>
                  <div className="mt-4 rounded-[24px] border border-[rgba(167,165,255,0.2)] bg-[linear-gradient(180deg,#201f1f_0%,#18181d_100%)] p-4">
                    <div className="flex justify-center">
                      <div
                        className="relative h-32 w-32 rounded-full"
                        style={{
                          background: `conic-gradient(#a7a5ff ${liveConfidence * 3.6}deg, #2a2a33 0deg)`
                        }}
                      >
                        <div className="absolute inset-[9px] flex flex-col items-center justify-center rounded-full bg-[#141416]">
                          <p className="text-4xl font-semibold tracking-tight text-[#e0dcff]">{liveConfidence}%</p>
                          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8e8fff]">{confidenceLabel}</p>
                        </div>
                      </div>
                    </div>
                    <p className="mt-3 text-center text-[11px] font-semibold text-[#9f9eff]">+ {performanceDelta}% from last session</p>
                  </div>
                  <p className="mt-4 text-center text-xs leading-5 text-slate-400">
                    You are sounding articulate and composed. Keep maintaining this pace.
                  </p>
                </div>

                <div className="mt-7">
                  <p className="ui-label text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Key Skills Tracked</p>
                  <div className="mt-4 space-y-4 rounded-[24px] bg-[rgba(19,19,19,0.72)] p-4">
                    {traitMetrics.map((trait) => (
                      <div key={trait.name}>
                        <div className="mb-1.5 flex items-center justify-between gap-2">
                          <p className="text-sm font-medium text-slate-200">{trait.name}</p>
                          <span className={`ui-label text-[10px] font-semibold uppercase tracking-[0.08em] ${trait.levelClass}`}>{trait.level}</span>
                        </div>
                        <div className="h-1.5 rounded-full bg-[#2b2b31]">
                          <span className={`block h-full rounded-full bg-gradient-to-r ${trait.barClass}`} style={{ width: `${trait.value}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mt-auto pt-8">
                  <div className="mb-5 rounded-[22px] border border-[rgba(167,165,255,0.2)] bg-[rgba(32,31,31,0.88)] px-3 py-3">
                    <p className="ui-label text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">Next Milestone</p>
                    <p className="mt-1 text-xs text-slate-300">Mention CAP theorem trade-offs to boost your architecture score.</p>
                  </div>
                  <div className="rounded-[22px] border border-[rgba(167,165,255,0.2)] bg-[rgba(32,31,31,0.88)] px-3 py-3">
                    <p className="ui-label text-[10px] font-semibold uppercase tracking-[0.12em] text-[#8b87c9]">Session Insights</p>
                    <ul className="mt-2 space-y-1.5 text-xs text-slate-300">
                      {sessionInsights.map((insight, idx) => (
                        <li key={idx} className="leading-5">- {insight}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            </aside>
          )
        ) : (
          <aside
            className={`min-h-0 flex-shrink-0 overflow-hidden transition-all duration-300 ${
              historyOpen ? "w-[320px] opacity-100" : "w-0 opacity-0 pointer-events-none"
            }`}
          >
            <div className="flex h-full min-h-0 flex-col rounded-3xl border border-slate-800 bg-[#08112e]">
              <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
                <div>
                  <p className="text-base font-semibold text-slate-100">Chat History</p>
                  <p className="text-xs text-slate-400">Q&A sessions with Jarvis</p>
                </div>
                {!!historyItems.length && (
                  <button
                    type="button"
                    onClick={clearChatHistory}
                    className="rounded-full border border-red-400/40 bg-red-500/10 px-3 py-1 text-xs font-medium text-red-300 transition hover:bg-red-500/20"
                  >
                    Clear
                  </button>
                )}
              </div>

              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
                {historyItems.length ? (
                  historyItems.map((item) => {
                    const messageCount = Array.isArray(item.chatMessages) ? item.chatMessages.length : 0;
                    const isActive = item.id === activeHistoryId;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => {
                          openHistory(item);
                          setHistoryOpen(false);
                        }}
                        className={`w-full rounded-2xl border px-3 py-2 text-left transition ${
                          isActive
                            ? "border-indigo-400/50 bg-indigo-500/15"
                            : "border-slate-700 bg-[#0d173a] hover:border-indigo-400/40"
                        }`}
                      >
                        <p className="truncate text-sm font-semibold text-slate-100">{item.title}</p>
                        <p className="mt-1 text-[11px] uppercase tracking-[0.08em] text-slate-400">
                          {new Date(item.updatedAt).toLocaleString()}
                        </p>
                        <p className="mt-1 text-xs text-slate-300">{messageCount} messages</p>
                      </button>
                    );
                  })
                ) : (
                  <div className="rounded-2xl border border-slate-700 bg-[#0d173a] p-4 text-sm text-slate-400">
                    No chat history yet. Start a session by uploading a JD and sending your first prompt.
                  </div>
                )}
              </div>
            </div>
          </aside>
        )}
      </div>
    </AppShell>
  );
}

