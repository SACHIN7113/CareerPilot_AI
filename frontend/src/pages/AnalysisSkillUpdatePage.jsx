import { useEffect, useMemo, useRef, useState } from "react";
import {
  FiArrowLeft,
  FiLoader,
  FiSearch,
} from "react-icons/fi";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { generateSkillRoadmap, startSkillUpdate } from "../api";
import AppShell from "../components/layout/AppShell";
import { notifyError } from "../utils/toast";

function buildRoadmapStepsForSkill(activeRoadmap, activeSkillContext) {
  if (activeRoadmap?.detailed_plan?.length) {
    const expanded = [];

    activeRoadmap.detailed_plan.forEach((phase, phaseIndex) => {
      const phaseName = String(phase?.phase || `Phase ${phaseIndex + 1}`);
      const phaseFocus = String(phase?.focus || "");
      const subtopics = Array.isArray(phase?.subtopics) ? phase.subtopics : [];
      const practice = Array.isArray(phase?.practice) ? phase.practice : [];

      if (subtopics.length) {
        subtopics.forEach((topic, topicIndex) => {
          const topicTitle = String(topic || "").trim();
          if (!topicTitle) return;
          expanded.push({
            id: `phase-${phaseIndex + 1}-topic-${topicIndex + 1}`,
            title: topicTitle,
            description: phaseFocus || `Part of ${phaseName}`,
            actionItems: [...practice, phaseFocus].filter(Boolean),
          });
        });
        return;
      }

      expanded.push({
        id: `phase-${phaseIndex + 1}`,
        title: phaseName,
        description: phaseFocus || "Complete this phase to move forward.",
        actionItems: practice,
      });
    });

    if (expanded.length) return expanded;
  }

  if (activeRoadmap?.roadmap_steps?.length) {
    const expanded = [];
    activeRoadmap.roadmap_steps.forEach((step, levelIndex) => {
      const levelName = String(step?.level || `Stage ${levelIndex + 1}`);
      const actionItems = Array.isArray(step?.action_items) ? step.action_items : [];

      if (actionItems.length) {
        actionItems.forEach((action, actionIndex) => {
          const actionTitle = String(action || "").trim();
          if (!actionTitle) return;
          expanded.push({
            id: `${step.step_id || `step-${levelIndex + 1}`}-action-${actionIndex + 1}`,
            title: actionTitle,
            description: `From ${levelName}`,
            actionItems: [actionTitle],
          });
        });
        return;
      }

      expanded.push({
        id: step.step_id || `step-${levelIndex + 1}`,
        title: step.title || step.step_title || levelName,
        description: step.description || "Complete this learning checkpoint.",
        actionItems: [],
      });
    });

    if (expanded.length) return expanded;
  }

  if (activeSkillContext?.how_to_fix?.length) {
    return activeSkillContext.how_to_fix.map((item, index) => ({
      id: `fix-${index + 1}`,
      title: `Learning Module ${index + 1}`,
      description: item,
      actionItems: [item],
    }));
  }

  return [];
}

function getStepCategoryLabel(step) {
  const text = [step?.title, step?.description, ...(Array.isArray(step?.actionItems) ? step.actionItems : [])]
    .join(" ")
    .toLowerCase();

  if (/(bios|uefi|hardware|device|driver)/.test(text)) return "HARDWARE AND OS DIAGNOSTICS";
  if (/(tcp|ip|network|packet|dns|http|socket)/.test(text)) return "NETWORK PROTOCOL ANALYSIS";
  if (/(filesystem|ntfs|ext4|storage|disk|volume)/.test(text)) return "STORAGE AND RECOVERY";
  if (/(json-rpc|mcp|tool|schema|resource|prompt|sdk)/.test(text)) return "MCP SERVER ENGINEERING";
  return "CORE SYSTEMS";
}

function getStepPillLabel(step) {
  const text = [step?.title, step?.description].join(" ").toLowerCase();

  if (/(network|tcp|ip|dns|http)/.test(text)) return "NETWORK";
  if (/(storage|filesystem|disk|volume|ntfs|ext4)/.test(text)) return "STORAGE";
  if (/(driver|hardware|bios|uefi)/.test(text)) return "HARDWARE";
  if (/(mcp|json-rpc|resource|tool|schema)/.test(text)) return "INFRASTRUCTURE";
  return "CORE SYSTEMS";
}
 
export default function AnalysisSkillUpdatePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();

  const analysisRecordId = searchParams.get("record") || "";
  const requestedSkill = searchParams.get("skill") || "";
  const requestedSkillFromQuery = String(requestedSkill || "").trim();
  const cacheKey = `jarvis_skill_lab_state_${analysisRecordId || "manual"}`;

  const [loadingContext, setLoadingContext] = useState(false);
  const [generatingRoadmap, setGeneratingRoadmap] = useState(false);
  const [contextData, setContextData] = useState(null);
  const [selectedSkill, setSelectedSkill] = useState("");
  const [roadmapsBySkill, setRoadmapsBySkill] = useState({});
  const [progressBySkill, setProgressBySkill] = useState({});
  const [customTargetInput, setCustomTargetInput] = useState("");
  const [customTargets, setCustomTargets] = useState([]);
  const [error, setError] = useState("");
  const [startingQuiz, setStartingQuiz] = useState(false);

  const appliedQuizAttemptRef = useRef(null);
  const roadmapsBySkillRef = useRef({});
  const inFlightRoadmapSkillsRef = useRef(new Set());

  const missingSkills = useMemo(
    () => (Array.isArray(contextData?.missing_skills) ? contextData.missing_skills : []),
    [contextData]
  );

  const allSkillTargets = useMemo(() => {
    const targets = new Set([...(missingSkills || []), ...(customTargets || [])]);
    return Array.from(targets);
  }, [missingSkills, customTargets]);

  const activeSkillContext = useMemo(
    () => contextData?.skill_details?.find((item) => item.skill === selectedSkill),
    [contextData, selectedSkill]
  );

  const activeRoadmap = selectedSkill ? roadmapsBySkill[selectedSkill] : null;

  const roadmapSteps = useMemo(
    () => buildRoadmapStepsForSkill(activeRoadmap, activeSkillContext),
    [activeRoadmap, activeSkillContext]
  );

  const selectedSkillProgress = progressBySkill[selectedSkill] || {
    completedStepIndexes: [],
    scores: {},
  };

  const completedCount = selectedSkillProgress.completedStepIndexes.length;
  const completionPct = roadmapSteps.length ? Math.round((completedCount / roadmapSteps.length) * 100) : 0;

  useEffect(() => {
    roadmapsBySkillRef.current = roadmapsBySkill || {};
  }, [roadmapsBySkill]);

  async function loadRoadmapForSkill(skill) {
    const targetSkill = String(skill || "").trim();
    if (!targetSkill) return;

    if (roadmapsBySkillRef.current[targetSkill]) return roadmapsBySkillRef.current[targetSkill];
    if (inFlightRoadmapSkillsRef.current.has(targetSkill)) return null;

    inFlightRoadmapSkillsRef.current.add(targetSkill);

    setGeneratingRoadmap(true);
    setError("");

    try {
      const payload = await generateSkillRoadmap(analysisRecordId || undefined, targetSkill);
      setRoadmapsBySkill((prev) => ({ ...prev, [targetSkill]: payload }));
      return payload;
    } catch (err) {
      setError(err.message || "Could not generate roadmap for the selected skill.");
      return null;
    } finally {
      inFlightRoadmapSkillsRef.current.delete(targetSkill);
      setGeneratingRoadmap(false);
    }
  }

  function selectSkill(skill) {
    const nextSkill = String(skill || "").trim();
    if (!nextSkill) return;
    setError("");
    setSelectedSkill(nextSkill);
  }

  function applyQuizResult(result) {
    if (!result?.selectedSkill) return;

    if (result?.coversAllSteps) {
      const totalSteps = Math.max(0, Number(result?.totalSteps || 0));
      setProgressBySkill((prev) => {
        const previous = prev[result.selectedSkill] || { completedStepIndexes: [], scores: {} };
        const completed = result?.passed
          ? Array.from({ length: totalSteps }, (_, index) => index)
          : previous.completedStepIndexes;

        return {
          ...prev,
          [result.selectedSkill]: {
            completedStepIndexes: completed,
            scores: {
              ...(previous.scores || {}),
              overall: result.scorePercent,
            },
          },
        };
      });
      return;
    }

    if (!Number.isInteger(result?.stepIndex)) return;

    setProgressBySkill((prev) => {
      const previous = prev[result.selectedSkill] || { completedStepIndexes: [], scores: {} };
      const completed = Array.from(new Set([...previous.completedStepIndexes, result.stepIndex])).sort((a, b) => a - b);

      return {
        ...prev,
        [result.selectedSkill]: {
          completedStepIndexes: completed,
          scores: {
            ...(previous.scores || {}),
            [result.stepIndex]: result.scorePercent,
          },
        },
      };
    });
  }

  function buildReturnPath(skill) {
    const params = new URLSearchParams();
    if (analysisRecordId) params.set("record", analysisRecordId);
    if (skill) params.set("skill", skill);

    const query = params.toString();
    return query ? `/analysis/skill-update?${query}` : "/analysis/skill-update";
  }

  async function openSkillWideQuiz(skillInput = selectedSkill) {
    const targetSkill = String(skillInput || "").trim();
    if (!targetSkill) return;

    setStartingQuiz(true);
    setError("");
    setSelectedSkill(targetSkill);

    try {
      const roadmap = roadmapsBySkillRef.current[targetSkill] || (await loadRoadmapForSkill(targetSkill));
      const targetSkillContext = contextData?.skill_details?.find((item) => item.skill === targetSkill) || null;
      const steps = buildRoadmapStepsForSkill(roadmap, targetSkillContext);

      if (!steps.length) {
        setError(`Could not find roadmap topics for ${targetSkill}. Please generate the roadmap first.`);
        return;
      }

      const topicPool = Array.from(
        new Set(
          steps
            .flatMap((item) => [
              item?.title,
              item?.description,
              ...(Array.isArray(item?.actionItems) ? item.actionItems : []),
            ])
            .map((item) => String(item || "").trim())
            .filter(Boolean)
            .filter((item) => item.length > 3)
            .filter((item) => !/^(ai-generated|mcq|quiz|comprehensive checkpoint)/i.test(item))
        )
      );

      const dynamicQuestionCount = Math.min(20, Math.max(10, Math.ceil(topicPool.length / 2)));

      const skillWideStep = {
        id: `skill-wide-${targetSkill.toLowerCase().replace(/\s+/g, "-")}`,
        title: `${targetSkill} assessment`,
        description: `Comprehensive assessment for ${targetSkill} roadmap topics.`,
        actionItems: topicPool,
      };

      navigate("/analysis/skill-quiz", {
        state: {
          analysisRecordId,
          selectedSkill: targetSkill,
          step: skillWideStep,
          stepIndex: -1,
          totalSteps: steps.length,
          questionCount: dynamicQuestionCount,
          coversAllSteps: true,
          returnTo: buildReturnPath(targetSkill),
          restoreState: {
            selectedSkill: targetSkill,
            contextData,
            roadmapsBySkill,
            progressBySkill,
            customTargets,
            customTargetInput,
            analysisRecordId,
          },
        },
      });
    } finally {
      setStartingQuiz(false);
    }
  }

  async function handleGenerateCustomTarget() {
    const target = String(customTargetInput || "").trim();
    if (!target) return;

    setCustomTargets((prev) => (prev.includes(target) ? prev : [...prev, target]));
    selectSkill(target);
    await loadRoadmapForSkill(target);
    setCustomTargetInput("");
  }

  useEffect(() => {
    const restored = location.state?.restoreState;

    if (restored) {
      if (restored.contextData) setContextData(restored.contextData);
      if (requestedSkillFromQuery) {
        setSelectedSkill(requestedSkillFromQuery);
      } else if (restored.selectedSkill) {
        setSelectedSkill(restored.selectedSkill);
      }
      if (restored.roadmapsBySkill) {
        roadmapsBySkillRef.current = restored.roadmapsBySkill;
        setRoadmapsBySkill(restored.roadmapsBySkill);
      }
      if (restored.progressBySkill) setProgressBySkill(restored.progressBySkill);
      if (restored.customTargets) setCustomTargets(restored.customTargets);
      if (restored.customTargetInput) setCustomTargetInput(restored.customTargetInput);
    } else {
      try {
        const raw = sessionStorage.getItem(cacheKey);
        if (raw) {
          const cached = JSON.parse(raw);
          if (cached?.contextData) setContextData(cached.contextData);
          if (requestedSkillFromQuery) {
            setSelectedSkill(requestedSkillFromQuery);
          } else if (cached?.selectedSkill) {
            setSelectedSkill(cached.selectedSkill);
          }
          if (cached?.roadmapsBySkill) {
            roadmapsBySkillRef.current = cached.roadmapsBySkill;
            setRoadmapsBySkill(cached.roadmapsBySkill);
          }
          if (cached?.progressBySkill) setProgressBySkill(cached.progressBySkill);
          if (cached?.customTargets) setCustomTargets(cached.customTargets);
        } else if (requestedSkillFromQuery) {
          setSelectedSkill(requestedSkillFromQuery);
        }
      } catch {
        sessionStorage.removeItem(cacheKey);
      }
    }

    const quizResult = location.state?.quizResult;
    if (quizResult?.attemptId && quizResult.attemptId !== appliedQuizAttemptRef.current) {
      appliedQuizAttemptRef.current = quizResult.attemptId;
      applyQuizResult(quizResult);
      setSelectedSkill((prev) => quizResult.selectedSkill || prev);
    }
  }, [location.state, cacheKey, requestedSkillFromQuery]);

  useEffect(() => {
    if (!analysisRecordId) {
      setLoadingContext(false);
      return;
    }

    if (contextData) {
      setLoadingContext(false);
      return;
    }

    let active = true;

    async function loadSkillContext() {
      setLoadingContext(true);
      setError("");

      try {
        const payload = await startSkillUpdate(analysisRecordId);
        if (!active) return;

        setContextData(payload);
        setSelectedSkill((prev) => requestedSkillFromQuery || prev || payload?.missing_skills?.[0] || "");
      } catch (err) {
        if (active) {
          setError(err.message || "Could not load missing skills.");
        }
      } finally {
        if (active) {
          setLoadingContext(false);
        }
      }
    }

    loadSkillContext();

    return () => {
      active = false;
    };
  }, [analysisRecordId, requestedSkillFromQuery, contextData]);

  useEffect(() => {
    if (!selectedSkill) return;
    loadRoadmapForSkill(selectedSkill);
  }, [selectedSkill]);

  useEffect(() => {
    if (!error) return;
    notifyError(error);
  }, [error]);

  useEffect(() => {
    try {
      sessionStorage.setItem(
        cacheKey,
        JSON.stringify({
          selectedSkill,
          contextData,
          roadmapsBySkill,
          progressBySkill,
          customTargets,
        })
      );
    } catch {
      // Ignore persistence errors.
    }
  }, [cacheKey, selectedSkill, contextData, roadmapsBySkill, progressBySkill, customTargets]);

  return (
    <AppShell
      title="Skill Lab"
      subtitle="Deep dive into one skill gap at a time with a clear roadmap."
      fullBleed
      darkShell
    >
      <div className="flex min-h-0 flex-1 flex-col gap-8 overflow-y-auto px-1 pb-8 pr-1 sm:px-3">
        {!analysisRecordId && (
          <div className="rounded-xl border border-amber-400/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            No analysis context detected. Enter any skill or role below to generate a custom learning roadmap.
          </div>
        )}
        <section className="pt-2">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <span className="inline-flex rounded-full border border-[#6142ba] bg-[#6b46c11f] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#b69cff]">
                Adaptive Skill Track
              </span>
              <h1 className="mt-4 text-[52px] font-extrabold leading-[0.95] tracking-tight text-white sm:text-[42px]">{selectedSkill || "Troubleshooting"}</h1>
              <p className="mt-4 max-w-2xl text-[18px] leading-8 text-[#a9adbb]">
                Master the art of diagnostic reasoning and systemic resolution across hardware and digital protocols.
              </p>
            </div>

            <div className="flex items-center gap-3 self-start">
              <button
                type="button"
                onClick={() => navigate("/analysis", { state: { preserveAnalysis: true } })}
                className="inline-flex items-center gap-2 rounded-xl border border-[#2d3240] bg-[#0c1018] px-3.5 py-2 text-sm font-medium text-[#d8dcec] transition hover:border-[#4a5164]"
              >
                <FiArrowLeft className="text-sm" />
                Back
              </button>

             
            </div>
          </div>

          <div className="mt-10 flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative flex-1 rounded-2xl bg-[#000000] p-1 shadow-[inset_0_1px_0_0_rgba(167,165,255,0.16)]">
              <FiSearch className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#7f869a]" />
              <input
                value={customTargetInput}
                onChange={(event) => setCustomTargetInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    handleGenerateCustomTarget();
                  }
                }}
                placeholder="Search specific skills or infrastructure roles..."
                className="h-12 w-full rounded-xl border-0 bg-transparent py-2 pl-11 pr-4 text-sm text-[#f0f2fb] outline-none transition placeholder:text-[#5c6477]"
              />
            </div>
            <button
              type="button"
              onClick={() => openSkillWideQuiz()}
              disabled={startingQuiz || generatingRoadmap || !selectedSkill}
              className="h-12 rounded-xl border border-transparent bg-[linear-gradient(135deg,#a7a5ff,#645efb)] px-9 text-sm font-bold text-white shadow-[0_0_20px_rgba(167,165,255,0.25)] transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55"
            >
              {startingQuiz ? "Starting..." : "Take Quiz"}
            </button>
          </div>
        </section>

        {loadingContext && (
          <section className="flex min-h-[calc(100vh-320px)] items-center justify-center rounded-[28px] border border-[#1b1f2a] bg-[#06070b] px-6 py-8 text-center">
            <div>
              <FiLoader className="mx-auto animate-spin text-2xl text-[#8d93ff]" />
              <p className="mt-3 text-sm text-[#8f95a6]">Preparing your skill roadmap...</p>
            </div>
          </section>
        )}

        {!loadingContext && (
          <section>
            <div>
              <h2 className="text-[36px] font-bold leading-none tracking-tight text-white sm:text-[36px]">Learning Path</h2>
              <div className="mt-3 h-1 w-12 rounded-full bg-[#a7a5ff]" />
            </div>

            {generatingRoadmap ? (
              <div className="mt-6 rounded-2xl border border-[#252b37] bg-[#10131a] px-4 py-5 text-sm text-[#9ca3b6]">
                <div className="inline-flex items-center gap-2 text-[#b6c3ff]">
                  <FiLoader className="animate-spin" />
                  Generating learning path for {selectedSkill || "selected skill"}...
                </div>
                <p className="mt-2 text-xs uppercase tracking-[0.14em] text-[#6f768b]">
                  AI is creating roadmap phases and actionable checkpoints.
                </p>
              </div>
            ) : roadmapSteps.length > 0 ? (
              <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
                {roadmapSteps.map((step, index) => (
                  <article
                    key={step.id}
                    className="group flex h-full flex-col rounded-[2rem] border border-white/5 bg-[rgba(38,38,38,0.4)] p-8 backdrop-blur-[24px] shadow-[inset_0_1px_0_0_rgba(167,165,255,0.15)] transition hover:border-[rgba(167,165,255,0.25)]"
                  >
                    <div className="mb-10 flex items-start justify-between gap-3">
                      <p className="text-3xl font-black leading-none tracking-tight text-[rgba(167,165,255,0.22)] group-hover:text-[#a7a5ff]">
                        {String(index + 1).padStart(3, "0")}
                      </p>
                      <span className="rounded-full bg-[#262626] px-3 py-1 text-[10px] font-bold uppercase tracking-[0.1em] text-[#a9adbb]">
                        {getStepPillLabel(step)}
                      </span>
                    </div>

                    <h3 className="text-3xl font-bold leading-tight text-white sm:text-[28px]">{step.title}</h3>
                    <p className="mb-8 mt-3 flex-1 text-base leading-7 text-[#a3a8b6]">{step.description}</p>

                    <div className="border-t border-white/5 pt-6">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#7f8597]">{getStepCategoryLabel(step)}</p>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="mt-6 rounded-2xl border border-[#252b37] bg-[#10131a] px-4 py-4 text-sm text-[#9ca3b6]">
                No roadmap steps found yet. Select another skill or enter a custom target to load a path.
              </div>
            )}
          </section>
        )}
      </div>
    </AppShell>
  );
}
