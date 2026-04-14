import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

from app.config.settings import settings
from app.core.async_utils import run_blocking
from app.services.gemini_service import (
    _extract_text_sync as extract_text,
    _generation_model_names_sync as generation_model_names,
    _get_model_sync as get_model,
    _parse_json_response_sync as parse_json_response,
)


ROADMAP_VERSION = 2


def _generate_json_with_timeout(*, model: Any, prompt: str, context: str, timeout_seconds: float = 14.0):
    executor = ThreadPoolExecutor(max_workers=1)
    generation_config = {"temperature": 0.2, "response_mime_type": "application/json"}
    future = executor.submit(model.generate_content, f"{prompt}\n\n{context}", generation_config=generation_config)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        future.cancel()
        return None
    except Exception:
        return None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _candidate_model_names() -> list[str]:
    return generation_model_names(preferred_models=["models/gemini-2.5-flash"])


def _infer_roadmap_domain(target: str) -> str:
    lowered = str(target or "").lower()
    if re.search(r"\b(windows|linux|ubuntu|macos|operating system|command prompt|powershell|terminal|shell)\b", lowered):
        return "os"
    if re.search(r"\b(communication|english|speaking|pronunciation|grammar|tense|vocabulary|interpersonal|presentation|body language)\b", lowered):
        return "communication"
    if re.search(r"\b(python|java|javascript|typescript|react|angular|node|sql|backend|frontend|devops|cloud|api)\b", lowered):
        return "technical"
    return "general"


def _roadmap_style_guidance(*, target: str, domain: str) -> str:
    if domain == "os":
        return (
            "Target is operating-system learning. Keep roadmap practical and daily-use focused: navigation, file management, "
            "settings, security, troubleshooting, and essential command-line usage. Avoid interview prep, resume bullets, "
            "portfolio projects, or corporate system-design content unless explicitly requested by target."
        )
    if domain == "communication":
        return (
            "Target is communication skill development. Focus on grammar (especially tenses), speaking practice, listening, "
            "pronunciation, vocabulary building, confidence, and real conversation drills. Keep steps habit-driven with "
            "measurable daily/weekly practice actions."
        )
    if domain == "technical":
        return (
            "Target is a technical skill. Include practical build tasks and debugging practice. Interview or project preparation "
            "is allowed only in advanced phases, not in every phase."
        )
    return (
        "Create a practical roadmap aligned to the target domain and learner intent. Avoid boilerplate phrases and generic "
        "one-size-fits-all milestones."
    )


def _build_missing_skill_details_sync(
    *,
    missing_skills: list[str],
    jd_text: str,
    resume_text: str,
) -> list[dict[str, Any]]:
    clean_missing = _clean_unique_list(missing_skills, max_items=12)
    if not clean_missing:
        return []

    llm_items = _llm_missing_skill_details(clean_missing, jd_text=jd_text, resume_text=resume_text)
    if llm_items:
        return llm_items

    return [_fallback_skill_detail(skill) for skill in clean_missing]


def _build_skill_roadmap_sync(
    *,
    target: str,
) -> dict[str, Any]:
    clean_target = _clean_text(target, max_len=80)
    if not clean_target:
        raise ValueError("Please provide a skill or role to learn.")

    llm_result = _llm_skill_roadmap(
        target=clean_target,
    )
    if llm_result:
        return llm_result

    return _fallback_roadmap(clean_target)


async def build_missing_skill_details_async(
    *,
    missing_skills: list[str],
    jd_text: str,
    resume_text: str,
) -> list[dict[str, Any]]:
    return await run_blocking(
        _build_missing_skill_details_sync,
        missing_skills=missing_skills,
        jd_text=jd_text,
        resume_text=resume_text,
    )


async def build_skill_roadmap_async(
    *,
    target: str,
) -> dict[str, Any]:
    return await run_blocking(_build_skill_roadmap_sync, target=target)


async def build_missing_skill_details(
    *,
    missing_skills: list[str],
    jd_text: str,
    resume_text: str,
) -> list[dict[str, Any]]:
    return await build_missing_skill_details_async(
        missing_skills=missing_skills,
        jd_text=jd_text,
        resume_text=resume_text,
    )


async def build_skill_roadmap(
    *,
    target: str,
) -> dict[str, Any]:
    return await build_skill_roadmap_async(target=target)


def _build_skill_step_assessment_sync(
    *,
    target: str,
    step_title: str,
    step_description: str,
    action_items: list[str],
    question_count: int,
) -> dict[str, Any]:
    clean_target = _clean_text(target, max_len=120)
    clean_title = _clean_text(step_title, max_len=140)
    clean_description = _clean_text(step_description, max_len=700)
    clean_actions = _clean_unique_list(action_items, max_items=80)
    filtered_actions = _filter_assessment_topics(action_items=clean_actions, target=clean_target, step_title=clean_title)

    if not clean_target:
        raise ValueError("Please provide a valid skill or role target.")
    if not clean_title:
        raise ValueError("Step title is required to generate this assessment.")

    requested_count = max(5, min(20, int(question_count or 10)))
    # For skill-wide quizzes with many topics, broaden question count to improve coverage.
    coverage_target = min(20, max(10, len(filtered_actions))) if filtered_actions else requested_count
    safe_count = max(requested_count, coverage_target)

    llm_result = _llm_skill_step_assessment(
        target=clean_target,
        step_title=clean_title,
        step_description=clean_description,
        action_items=filtered_actions,
        question_count=safe_count,
    )
    if llm_result:
        llm_questions = _filter_relevant_questions(
            llm_result.get("questions", []),
            target=clean_target,
            step_title=clean_title,
            action_items=filtered_actions,
        )
        if len(llm_questions) < safe_count:
            supplemental = _fallback_skill_questions(
                target=clean_target,
                step_title=clean_title,
                key_points=llm_result.get("key_points", []),
                question_count=safe_count,
            )
            llm_questions = _merge_questions(primary=llm_questions, supplemental=supplemental, max_count=safe_count)

        llm_result["questions"] = _reindex_questions(llm_questions[:safe_count])
        return llm_result

    return _fallback_skill_step_assessment(
        target=clean_target,
        step_title=clean_title,
        step_description=clean_description,
        action_items=filtered_actions,
        question_count=safe_count,
    )


async def build_skill_step_assessment_async(
    *,
    target: str,
    step_title: str,
    step_description: str,
    action_items: list[str],
    question_count: int,
) -> dict[str, Any]:
    return await run_blocking(
        _build_skill_step_assessment_sync,
        target=target,
        step_title=step_title,
        step_description=step_description,
        action_items=action_items,
        question_count=question_count,
    )


async def build_skill_step_assessment(
    *,
    target: str,
    step_title: str,
    step_description: str,
    action_items: list[str],
    question_count: int,
) -> dict[str, Any]:
    return await build_skill_step_assessment_async(
        target=target,
        step_title=step_title,
        step_description=step_description,
        action_items=action_items,
        question_count=question_count,
    )


def _llm_missing_skill_details(missing_skills: list[str], *, jd_text: str, resume_text: str) -> list[dict[str, Any]]:
    prompt = (
        "You are a career mentor. Explain missing JD skills simply for students. "
        "Return strict JSON only with key skill_details, where skill_details is an array of objects. "
        "Each object must have: skill, why_missing, how_to_fix (array of 3-4 short actions)."
    )
    context = (
        f"Missing skills: {', '.join(missing_skills)}\n\n"
        f"Job Description:\n{jd_text[:5000]}\n\n"
        f"Resume:\n{resume_text[:3500]}"
    )

    for model_name in _candidate_model_names():
        model = get_model(model_name)
        if model is None:
            continue

        try:
            response = _generate_json_with_timeout(
                model=model,
                prompt=prompt,
                context=context,
                timeout_seconds=10.0,
            )
            if response is None:
                continue
            parsed = parse_json_response(extract_text(response) or "{}")
            raw_items = parsed.get("skill_details") if isinstance(parsed, dict) else None
            if not isinstance(raw_items, list):
                continue

            cleaned: list[dict[str, Any]] = []
            missing_set = {item.lower() for item in missing_skills}
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                skill = _clean_text(item.get("skill"), max_len=50)
                if not skill:
                    continue
                if skill.lower() not in missing_set and len(cleaned) < len(missing_skills):
                    # Keep LLM-provided aliases if they are close to missing skills.
                    if not any(skill.lower() in miss.lower() or miss.lower() in skill.lower() for miss in missing_skills):
                        continue

                why_missing = _clean_text(item.get("why_missing"), max_len=220)
                how_to_fix = _clean_unique_list(item.get("how_to_fix"), max_items=4)
                if not why_missing:
                    why_missing = f"This skill is expected in the JD, but your resume does not show enough evidence for {skill}."
                if not how_to_fix:
                    how_to_fix = _fallback_fix_steps(skill)

                cleaned.append(
                    {
                        "skill": skill,
                        "why_missing": why_missing,
                        "how_to_fix": how_to_fix,
                    }
                )
                if len(cleaned) >= len(missing_skills):
                    break

            if cleaned:
                return cleaned
        except Exception:
            continue

    return []


def _llm_skill_roadmap(
    *,
    target: str,
) -> dict[str, Any] | None:
    domain = _infer_roadmap_domain(target)
    domain_guidance = _roadmap_style_guidance(target=target, domain=domain)

    prompt = (
        "Create a clear student-friendly roadmap from beginner to job-ready level for the target skill/role. "
        "Roadmap must be based only on the given target, not on any JD, resume, or hiring text. "
        "Roadmap must be domain-specific and should not repeat a generic template across unrelated skills. "
        "Return strict JSON only with keys: target, overview, roadmap_steps, detailed_plan, projects, resources, flowchart_text. "
        "roadmap_steps must be an array of exactly 4 objects with keys level and action_items. "
        "Use levels: Beginner, Intermediate, Advanced, Expert. "
        "action_items should be a list of 3-5 concise actions. "
        "detailed_plan must be an array of 4 to 6 objects with keys: phase, focus, subtopics, practice. "
        "subtopics should be 3-5 items, practice should be 2-4 items. "
        "Avoid placeholders like 'core concepts', 'common patterns', or 'interview prep' unless target explicitly requires them. "
        "flowchart_text must follow this exact style with connected nodes and arrows: "
        "Start\\n  ↓\\nTopic\\n  ↓\\n(Subtopic → Subtopic) ... and must end with END (Job Ready <target> 🚀)."
    )
    context = (
        f"Target: {target}\n"
        f"Detected domain: {domain}\n"
        f"Guidance: {domain_guidance}"
    )

    for model_name in _candidate_model_names():
        model = get_model(model_name)
        if model is None:
            continue

        try:
            response = _generate_json_with_timeout(
                model=model,
                prompt=prompt,
                context=context,
                timeout_seconds=12.0,
            )
            if response is None:
                continue
            parsed = parse_json_response(extract_text(response) or "{}")
            if not isinstance(parsed, dict):
                continue

            target_out = _clean_text(parsed.get("target") or target, max_len=80)
            overview = _clean_text(parsed.get("overview"), max_len=450)
            roadmap_steps = _clean_roadmap_steps(parsed.get("roadmap_steps"))
            detailed_plan = _clean_detailed_plan(parsed.get("detailed_plan"))
            projects = _clean_unique_list(parsed.get("projects"), max_items=5)
            resources = _clean_unique_list(parsed.get("resources"), max_items=6)

            if not overview or not roadmap_steps:
                continue
            if not detailed_plan:
                detailed_plan = _fallback_detailed_plan(target_out)
            flowchart_text = _build_flowchart_text(target_out, detailed_plan)

            return {
                "target": target_out,
                "overview": overview,
                "roadmap_steps": roadmap_steps,
                "detailed_plan": detailed_plan,
                "flowchart_text": flowchart_text,
                "projects": projects,
                "resources": resources,
                "generated_by": f"llm:{model_name}",
                "roadmap_version": ROADMAP_VERSION,
            }
        except Exception:
            continue

    return None


def _llm_skill_step_assessment(
    *,
    target: str,
    step_title: str,
    step_description: str,
    action_items: list[str],
    question_count: int,
) -> dict[str, Any] | None:
    prompt = (
        "You are an expert teacher for job-ready skill building. "
        "Given the target skill/role and one learning step, return strict JSON only with keys: "
        "learning_content, key_points, questions. "
        "learning_content should be 140-260 words in simple student-friendly language. "
        "key_points must be an array of 5-8 concise bullets. "
        "questions must be an array with exactly the requested question count. "
        "Each question object must contain: question, options (exactly 4 strings), correct_option_index (0..3), explanation. "
        "All questions must be based directly on the provided step content and key points. "
        "Questions must collectively cover the breadth of provided action items/topics (not only one narrow area). "
        "Each MCQ must have exactly one unambiguously correct answer. "
        "Avoid generic stems like 'What do you understand by ...' and avoid placeholder wording like 'checkpoint topic'. "
        "Prefer practical, scenario-oriented, concept-application questions aligned to the target skill."
    )
    context = (
        f"Target: {target}\n"
        f"Step Title: {step_title}\n"
        f"Step Description: {step_description}\n"
        f"Action Items: {action_items}\n"
        f"Question Count: {question_count}"
    )

    for model_name in _candidate_model_names():
        model = get_model(model_name)
        if model is None:
            continue

        try:
            response = _generate_json_with_timeout(
                model=model,
                prompt=prompt,
                context=context,
                timeout_seconds=12.0,
            )
            if response is None:
                continue
            parsed = parse_json_response(extract_text(response) or "{}")
            if not isinstance(parsed, dict):
                continue

            learning_content = _clean_text(parsed.get("learning_content"), max_len=1800)
            key_points = _clean_unique_list(parsed.get("key_points"), max_items=8)
            questions = _clean_skill_step_questions(parsed.get("questions"), question_count=question_count)

            if not learning_content or len(questions) < 5:
                continue
            if not key_points:
                key_points = _derive_key_points(step_title=step_title, step_description=step_description, action_items=action_items)

            return {
                "target": target,
                "step_title": step_title,
                "learning_content": learning_content,
                "key_points": key_points,
                "questions": questions,
                "pass_threshold": 60,
                "generated_by": f"llm:{model_name}",
            }
        except Exception:
            continue

    return None


def _fallback_skill_detail(skill: str) -> dict[str, Any]:
    return {
        "skill": skill,
        "why_missing": f"This skill appears as a requirement in the JD, but there is limited proof of {skill} in your resume.",
        "how_to_fix": _fallback_fix_steps(skill),
    }


def _fallback_fix_steps(skill: str) -> list[str]:
    return [
        f"Complete a focused beginner-to-intermediate course on {skill}.",
        f"Build one practical mini-project using {skill} and publish it on GitHub.",
        f"Add 2 resume bullet points showing where you used {skill} and the outcome.",
        f"Practice interview questions for {skill} with implementation examples.",
    ]


def _fallback_roadmap(target: str) -> dict[str, Any]:
    domain = _infer_roadmap_domain(target)
    detailed_plan = _fallback_detailed_plan(target)

    if domain == "os":
        overview = (
            f"This roadmap teaches {target} through practical daily workflows: system navigation, settings, security, "
            "troubleshooting, and essential command-line tasks."
        )
        roadmap_steps = [
            {
                "level": "Beginner",
                "action_items": [
                    "Understand desktop layout, start menu, taskbar, and core navigation.",
                    "Open, switch, and close applications efficiently.",
                    "Use basic personalization and accessibility settings.",
                ],
            },
            {
                "level": "Intermediate",
                "action_items": [
                    "Manage files, folders, copy/move/rename, and quick search.",
                    "Use keyboard shortcuts for daily productivity.",
                    "Configure network, display, sound, and app settings safely.",
                ],
            },
            {
                "level": "Advanced",
                "action_items": [
                    "Use Task Manager and system tools to diagnose slow performance.",
                    "Apply basic troubleshooting for updates, startup, and connectivity.",
                    "Use command line (dir, cd, cls, ipconfig, ping) for diagnostics.",
                ],
            },
            {
                "level": "Expert",
                "action_items": [
                    "Harden security using updates, Defender, and account hygiene.",
                    "Create repeatable troubleshooting checklists for common issues.",
                    "Practice real scenarios and recover systems with confidence.",
                ],
            },
        ]
        projects = [
            "Weekly practical lab: optimize one PC and document before/after improvements",
            "Troubleshooting playbook: 20 common Windows issues with step-by-step fixes",
            "Security checklist: monthly OS maintenance and update workflow",
        ]
        resources = [
            "Microsoft Windows official documentation",
            "Windows keyboard shortcuts reference",
            "Microsoft Learn modules for Windows fundamentals",
        ]
    elif domain == "communication":
        overview = (
            f"This roadmap builds {target} with daily speaking habits, grammar foundations, listening drills, "
            "and confidence practice for real conversations."
        )
        roadmap_steps = [
            {
                "level": "Beginner",
                "action_items": [
                    "Learn core grammar with present, past, and future tense basics.",
                    "Build a daily vocabulary list with example sentences.",
                    "Practice short self-introductions and common conversation starters.",
                ],
            },
            {
                "level": "Intermediate",
                "action_items": [
                    "Practice speaking for 10-15 minutes daily on familiar topics.",
                    "Train listening using short videos/podcasts and repeat aloud.",
                    "Improve pronunciation and sentence stress with shadowing exercises.",
                ],
            },
            {
                "level": "Advanced",
                "action_items": [
                    "Handle structured discussions with clear opening-body-closing flow.",
                    "Use transition phrases and concise explanations in conversations.",
                    "Practice confidence, body language, and spontaneous speaking prompts.",
                ],
            },
            {
                "level": "Expert",
                "action_items": [
                    "Run mock interviews and feedback loops for clarity and impact.",
                    "Lead discussion practice sessions and summarize key points confidently.",
                    "Create a personal speaking improvement tracker and weekly review plan.",
                ],
            },
        ]
        projects = [
            "30-day speaking challenge with daily 2-minute recordings",
            "Conversation journal: convert daily events into clear spoken summaries",
            "Mock interview practice set with self-review checklist",
        ]
        resources = [
            "Grammar practice workbook focused on tense usage",
            "Pronunciation and listening channels/podcasts",
            "Peer speaking groups or conversation clubs",
        ]
    else:
        overview = (
            f"This roadmap helps you learn {target} step by step. Follow each level in order and keep building projects "
            "to prove your practical skills in interviews and resume."
        )
        roadmap_steps = [
            {
                "level": "Beginner",
                "action_items": [
                    f"Learn the core concepts and terminology of {target}.",
                    "Complete guided tutorials and write short notes.",
                    "Solve basic exercises daily to build confidence.",
                ],
            },
            {
                "level": "Intermediate",
                "action_items": [
                    f"Build 1 to 2 mini projects using {target}.",
                    "Practice debugging and common real-world problems.",
                    "Start explaining your approach in simple interview language.",
                ],
            },
            {
                "level": "Advanced",
                "action_items": [
                    "Implement a complete project with production-like structure.",
                    "Optimize performance, testing, and reliability.",
                    "Write resume bullets with measurable outcomes.",
                ],
            },
            {
                "level": "Expert",
                "action_items": [
                    "Design end-to-end solutions and justify trade-offs.",
                    "Teach others through documentation or short demos.",
                    "Prepare advanced interview scenarios and system-level discussions.",
                ],
            },
        ]
        projects = [
            f"Mini project: {target} fundamentals implementation",
            f"Intermediate project: practical {target} use-case",
            f"Capstone project: end-to-end {target} solution",
        ]
        resources = [
            "Official documentation",
            "Beginner to advanced online course",
            "Interview preparation question bank",
        ]

    return {
        "target": target,
        "overview": overview,
        "roadmap_steps": roadmap_steps,
        "detailed_plan": detailed_plan,
        "flowchart_text": _build_flowchart_text(target, detailed_plan),
        "projects": projects,
        "resources": resources,
        "generated_by": "fallback",
        "roadmap_version": ROADMAP_VERSION,
    }


def _fallback_skill_step_assessment(
    *,
    target: str,
    step_title: str,
    step_description: str,
    action_items: list[str],
    question_count: int,
) -> dict[str, Any]:
    key_points = _derive_key_points(step_title=step_title, step_description=step_description, action_items=action_items)
    learning_content = (
        f"This step focuses on {step_title} for {target}. Start with the foundational concepts, then apply them in short "
        "hands-on tasks. Make sure each concept is linked to a practical outcome, not only memorized. "
        f"Use the action items as checkpoints: {', '.join(action_items[:3]) if action_items else 'review basics, apply examples, and validate outcomes'}. "
        "After studying, explain the ideas in your own words and complete a small implementation task. "
        "This will help you retain knowledge and move confidently to the next roadmap stage."
    )
    questions = _fallback_skill_questions(
        target=target,
        step_title=step_title,
        key_points=key_points,
        question_count=question_count,
    )

    return {
        "target": target,
        "step_title": step_title,
        "learning_content": learning_content,
        "key_points": key_points,
        "questions": questions,
        "pass_threshold": 60,
        "generated_by": "fallback",
    }


def _clean_unique_list(value: Any, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_text(item, max_len=140)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= max_items:
            break
    return cleaned


def _clean_skill_step_questions(value: Any, *, question_count: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue

        question = _sanitize_question_text(_clean_text(item.get("question"), max_len=260))
        if not question:
            continue
        question_lower = question.lower()
        if "what do you understand by" in question_lower or "checkpoint topic" in question_lower:
            continue

        options_raw = item.get("options") if isinstance(item.get("options"), list) else []
        options = [_clean_text(option, max_len=200) for option in options_raw]
        options = [option for option in options if option]
        unique_options: list[str] = []
        seen_options: set[str] = set()
        for option in options:
            normalized = option.lower()
            if normalized in seen_options:
                continue
            seen_options.add(normalized)
            unique_options.append(option)
            if len(unique_options) == 4:
                break

        if len(unique_options) != 4:
            continue

        try:
            correct_option_index = int(
                item.get("correct_option_index", item.get("correctOptionIndex", item.get("answer_index")))
            )
        except (TypeError, ValueError):
            continue
        if correct_option_index < 0 or correct_option_index > 3:
            continue

        explanation = _clean_text(item.get("explanation"), max_len=260)
        cleaned.append(
            {
                "question_id": f"sq{index + 1}",
                "question": question,
                "options": unique_options,
                "correct_option_index": correct_option_index,
                "explanation": explanation,
            }
        )

        if len(cleaned) >= question_count:
            break

    return cleaned


def _derive_key_points(*, step_title: str, step_description: str, action_items: list[str]) -> list[str]:
    points: list[str] = []

    if step_title:
        points.append(f"Understand the core idea behind {step_title}.")
    if step_description and not _is_meta_learning_item(step_description):
        points.append(step_description)

    for action in action_items[:20]:
        if _is_meta_learning_item(action):
            continue
        points.append(action)

    if len(points) < 5:
        points.extend(
            [
                "Connect concepts with at least one practical use case.",
                "Practice with one small implementation task.",
                "Review common mistakes and how to avoid them.",
                "Summarize your learning in simple interview-ready language.",
            ]
        )

    return _clean_unique_list(points, max_items=20)


def _fallback_skill_questions(*, target: str, step_title: str, key_points: list[str], question_count: int) -> list[dict[str, Any]]:
    return _build_fallback_skill_questions(
        target=target,
        step_title=step_title,
        key_points=key_points,
        question_count=question_count,
    )


def _build_fallback_skill_questions(
    *,
    target: str,
    step_title: str,
    key_points: list[str],
    question_count: int,
) -> list[dict[str, Any]]:
    base_points = key_points[: max(5, min(max(8, question_count), len(key_points)))]
    if not base_points:
        base_points = [
            f"Understand the basics of {step_title}.",
            "Apply the concept in a mini task.",
            "Review errors and correct them.",
            "Measure progress with a small output.",
            "Explain the concept clearly.",
        ]

    distractor_templates = [
        "Skip validation for {topic} and assume one successful run is enough.",
        "Apply broad changes unrelated to {topic} before checking evidence.",
        "Treat {topic} as theory only and avoid practical verification.",
        "Ignore constraints of {topic} and rely on guesswork fixes.",
        "Optimize performance first without confirming {topic} correctness.",
        "Copy a solution for {topic} without adapting it to current requirements.",
    ]

    question_templates = [
        "When working on {skill}, which approach best handles '{topic}'?",
        "In a real {skill} task, what is the best next step for '{topic}'?",
        "Which statement about '{topic}' is most accurate for practical {skill} work?",
        "For {skill}, which option shows correct execution of '{topic}'?",
    ]

    correct_templates = [
        "Break down {topic}, apply a targeted solution, then verify with reproducible checks.",
        "Use documented constraints for {topic}, implement incrementally, and validate expected outcomes.",
        "Test {topic} with evidence (logs/results), fix root causes, and re-check end-to-end behavior.",
        "Implement {topic} with clear assumptions, run verification steps, and confirm stable output.",
    ]

    questions: list[dict[str, Any]] = []
    for index in range(question_count):
        topic = base_points[index % len(base_points)]
        clean_topic = _clean_text(topic, max_len=90) or "this concept"
        clean_skill = _clean_text(target, max_len=80) or _clean_text(step_title, max_len=80) or "this skill"

        question_text = question_templates[index % len(question_templates)].format(skill=clean_skill, topic=clean_topic)
        correct = correct_templates[index % len(correct_templates)].format(topic=clean_topic)

        topic_distractors = [
            template.format(topic=clean_topic.lower())
            for template in distractor_templates[index % len(distractor_templates):]
        ] + [
            template.format(topic=clean_topic.lower())
            for template in distractor_templates[: index % len(distractor_templates)]
        ]
        pool = topic_distractors
        options = [correct]
        for item in pool:
            if item not in options:
                options.append(item)
            if len(options) == 4:
                break

        if len(options) < 4:
            for item in topic_distractors:
                if item not in options:
                    options.append(item)
                if len(options) == 4:
                    break

        # Rotate so correct answer index is not always zero.
        correct_index = index % 4
        rotated = options[correct_index:] + options[:correct_index]
        actual_correct_index = rotated.index(correct)

        questions.append(
            {
                "question_id": f"sq{index + 1}",
                "question": _sanitize_question_text(question_text),
                "options": rotated,
                "correct_option_index": actual_correct_index,
                "explanation": f"This option best matches good practice for '{topic}'.",
            }
        )

    return questions


def _filter_assessment_topics(*, action_items: list[str], target: str, step_title: str) -> list[str]:
    topics: list[str] = []
    for item in action_items:
        clean_item = _clean_text(item, max_len=140)
        if not clean_item:
            continue
        if _is_meta_learning_item(clean_item):
            continue
        topics.append(clean_item)

    if not topics and step_title:
        topics.append(step_title)
    if not topics and target:
        topics.append(f"Core {target} concepts")

    return _clean_unique_list(topics, max_items=80)


def _filter_relevant_questions(
    questions: list[dict[str, Any]],
    *,
    target: str,
    step_title: str,
    action_items: list[str],
) -> list[dict[str, Any]]:
    if not questions:
        return []

    relevance_tokens: set[str] = set()
    for source in [target, step_title, *action_items[:30]]:
        text = _clean_text(source, max_len=140).lower()
        for token in re.findall(r"[a-z0-9+#.-]{4,}", text):
            relevance_tokens.add(token)

    if not relevance_tokens:
        return questions

    filtered: list[dict[str, Any]] = []
    for item in questions:
        question = _clean_text(item.get("question"), max_len=260)
        combined = " ".join(
            [
                question,
                " ".join(item.get("options", [])) if isinstance(item.get("options"), list) else "",
                _clean_text(item.get("explanation"), max_len=260),
            ]
        ).lower()
        if any(token in combined for token in relevance_tokens):
            filtered.append(item)

    return filtered


def _merge_questions(
    *,
    primary: list[dict[str, Any]],
    supplemental: list[dict[str, Any]],
    max_count: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for source in [primary, supplemental]:
        for question in source:
            stem = _clean_text(question.get("question"), max_len=260).lower()
            if not stem or stem in seen:
                continue
            seen.add(stem)
            merged.append(question)
            if len(merged) >= max_count:
                return merged

    return merged


def _reindex_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed: list[dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        next_item = dict(question)
        next_item["question_id"] = f"sq{index}"
        indexed.append(next_item)
    return indexed


def _is_meta_learning_item(text: str) -> bool:
    lowered = text.lower()
    blocked_fragments = (
        "ai-generated",
        "mcq",
        "quiz",
        "checkpoint topic",
        "choose the best option",
        "optional self-check",
        "roadmap topics",
    )
    return any(fragment in lowered for fragment in blocked_fragments)


def _sanitize_question_text(text: str) -> str:
    question = _clean_text(text, max_len=260)
    if not question:
        return ""

    question = re.sub(r"^in\s+.+?\s+assessment,\s*", "", question, flags=re.IGNORECASE)
    question = re.sub(r"^for\s+step\s+'.+?',\s*", "", question, flags=re.IGNORECASE)
    question = question.strip()

    if question and not question.endswith("?"):
        question = f"{question.rstrip('.')}?"

    return question


def _build_topic_question(*, step_title: str, topic: str) -> str:
    concise_topic = _clean_text(topic, max_len=90) or "this concept"
    concise_step = _clean_text(step_title, max_len=80) or "this skill"
    return f"In {concise_step}, which option best demonstrates solid understanding of '{concise_topic}'?"


def _build_correct_option(topic: str) -> str:
    concise_topic = _clean_text(topic, max_len=90) or "the topic"
    return f"Use {concise_topic.lower()} with evidence-driven steps and verify results after applying the fix."


def _build_distractor_option(topic: str) -> str:
    concise_topic = _clean_text(topic, max_len=90) or "the topic"
    return f"Prioritize speed over analysis for {concise_topic.lower()} and skip verification once changes are made."


def _clean_roadmap_steps(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    allowed_levels = {"beginner", "intermediate", "advanced", "expert"}
    cleaned: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        level = _clean_text(item.get("level"), max_len=40)
        if not level:
            continue

        if level.lower() not in allowed_levels:
            normalized = _normalize_level(level)
            if not normalized:
                continue
            level = normalized
        else:
            level = level.title()

        action_items = _clean_unique_list(item.get("action_items"), max_items=5)
        if not action_items:
            continue

        cleaned.append({"level": level, "action_items": action_items})

    if not cleaned:
        return []

    order = {"Beginner": 1, "Intermediate": 2, "Advanced": 3, "Expert": 4}
    cleaned.sort(key=lambda step: order.get(step["level"], 99))
    return cleaned[:4]


def _clean_detailed_plan(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    cleaned: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        phase = _clean_text(item.get("phase"), max_len=80)
        focus = _clean_text(item.get("focus"), max_len=220)
        subtopics = _clean_unique_list(item.get("subtopics"), max_items=6)
        practice = _clean_unique_list(item.get("practice"), max_items=4)

        if not phase or not subtopics:
            continue
        if not focus:
            focus = "Build this phase with practical implementation and revision."
        if not practice:
            practice = ["Build one mini project", "Solve implementation tasks and revise"]

        cleaned.append(
            {
                "phase": phase,
                "focus": focus,
                "subtopics": subtopics,
                "practice": practice,
            }
        )
        if len(cleaned) >= 6:
            break

    return cleaned


def _fallback_detailed_plan(target: str) -> list[dict[str, Any]]:
    label = target.lower()
    if re.search(r"\b(windows|linux|ubuntu|macos|operating system|command prompt|powershell|terminal|shell)\b", label):
        return [
            {
                "phase": "Step 1: Basics",
                "focus": "Get comfortable with navigation, desktop workflow, and daily usage tasks.",
                "subtopics": ["Start menu and taskbar", "Open/close apps", "Window management", "Settings overview"],
                "practice": ["Daily 15-minute navigation drills", "Personalize desktop settings"],
            },
            {
                "phase": "Step 2: File Management and Shortcuts",
                "focus": "Build speed with files/folders and keyboard productivity.",
                "subtopics": ["Create, rename, move, delete files", "Explorer search", "Clipboard workflow", "Shortcut keys"],
                "practice": ["Organize one folder hierarchy", "Use 10 shortcuts in routine work"],
            },
            {
                "phase": "Step 3: System Settings and Security",
                "focus": "Configure network, apps, updates, and baseline security safely.",
                "subtopics": ["Wi-Fi and network settings", "Display and audio", "Updates", "Defender and account safety"],
                "practice": ["Run update and reboot verification", "Apply basic security checklist"],
            },
            {
                "phase": "Step 4: Troubleshooting and Command Line",
                "focus": "Diagnose common issues and use essential CLI tools for checks.",
                "subtopics": ["Task Manager diagnostics", "Startup/app issue fixes", "Command Prompt basics", "Network checks (ipconfig/ping)"],
                "practice": ["Resolve 5 common issue scenarios", "Create a personal troubleshooting notebook"],
            },
        ]

    if re.search(r"\b(communication|english|speaking|pronunciation|grammar|tense|vocabulary|interpersonal|presentation|body language)\b", label):
        return [
            {
                "phase": "Step 1: Basic English Foundation",
                "focus": "Strengthen sentence structure, tense usage, and core vocabulary.",
                "subtopics": ["Present/past/future tenses", "Daily-use vocabulary", "Sentence framing", "Common grammar corrections"],
                "practice": ["Write and speak 10 daily sentences", "Tense correction drill"],
            },
            {
                "phase": "Step 2: Speaking and Listening Practice",
                "focus": "Build fluency through repetition, shadowing, and short speaking sessions.",
                "subtopics": ["Self-introduction", "Speak aloud routine", "Listening comprehension", "Pronunciation basics"],
                "practice": ["Record 2-minute daily speaking clips", "Shadow one short audio daily"],
            },
            {
                "phase": "Step 3: Confidence and Conversation",
                "focus": "Develop clarity, confidence, and spontaneous interaction skills.",
                "subtopics": ["Body language", "Conversation openers", "Follow-up questions", "Error recovery while speaking"],
                "practice": ["Mirror speaking exercise", "Weekly peer conversation"],
            },
            {
                "phase": "Step 4: Real-World Communication",
                "focus": "Apply communication in interviews, discussions, and professional settings.",
                "subtopics": ["Mock interview responses", "Group discussion structure", "Clear explanation method", "Feedback loop"],
                "practice": ["Two mock interviews per week", "Weekly improvement review"],
            },
        ]

    if "react" in label or "frontend" in label:
        return [
            {
                "phase": "Phase 1: Foundations",
                "focus": "Learn JavaScript basics and core web concepts used in modern frontend development.",
                "subtopics": ["ES6 Concepts", "Arrow Functions", "Destructuring", "Promises", "Async/Await"],
                "practice": ["Counter app", "Simple To-Do app"],
            },
            {
                "phase": "Phase 2: Core React",
                "focus": "Start building reusable components and managing UI state.",
                "subtopics": ["JSX", "Components", "Props", "useState", "useEffect"],
                "practice": ["Form validation app", "CRUD app"],
            },
            {
                "phase": "Phase 3: Advanced React",
                "focus": "Handle real app complexity and performance optimization.",
                "subtopics": ["React Router", "Context API", "Redux Toolkit", "Memoization", "Custom hooks"],
                "practice": ["Multi-page dashboard", "Admin panel UI"],
            },
            {
                "phase": "Phase 4: API & Deployment",
                "focus": "Integrate backend APIs and ship production-ready frontend projects.",
                "subtopics": ["Fetch API/Axios", "Error handling", "Auth flow", "Folder structure", "Deployment"],
                "practice": ["Blog app with API", "E-commerce frontend"],
            },
        ]

    return [
        {
            "phase": "Phase 1: Fundamentals",
            "focus": f"Build the core fundamentals and terminology of {target}.",
            "subtopics": ["Core concepts", "Basic syntax/tools", "Setup and workflow", "Common patterns"],
            "practice": ["Basic exercises", "Mini practice tasks"],
        },
        {
            "phase": "Phase 2: Core Skills",
            "focus": f"Apply {target} to solve practical, beginner-friendly problems.",
            "subtopics": ["Essential features", "Problem solving", "Debugging basics", "Code organization"],
            "practice": ["Mini project 1", "Mini project 2"],
        },
        {
            "phase": "Phase 3: Intermediate to Advanced",
            "focus": f"Build confidence in advanced workflows and real-world constraints in {target}.",
            "subtopics": ["Advanced patterns", "Performance basics", "Testing/quality", "Best practices"],
            "practice": ["Medium-scale project", "Scenario-based practice"],
        },
        {
            "phase": "Phase 4: Job-Ready Execution",
            "focus": "Create portfolio-ready projects and prepare interview-ready explanations.",
            "subtopics": ["Capstone project", "Portfolio polish", "Resume bullets", "Interview Q&A"],
            "practice": ["Capstone implementation", "Mock interview"],
        },
    ]


def _build_flowchart_text(target: str, detailed_plan: list[dict[str, Any]]) -> str:
    lines: list[str] = ["Start"]
    for phase in detailed_plan:
        phase_title = _clean_text(phase.get("phase"), max_len=80)
        subtopics = _clean_unique_list(phase.get("subtopics"), max_items=6)
        if not phase_title or not subtopics:
            continue

        lines.append("  ↓")
        lines.append(phase_title)
        lines.append("  ↓")
        lines.append(f"({' → '.join(subtopics)})")

    lines.append("  ↓")
    lines.append(f"END (Job Ready {target} 🚀)")
    return "\n".join(lines)


def _clean_flowchart_text(value: Any, *, target: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return ""

    if lines[0].strip().lower() != "start":
        lines.insert(0, "Start")

    end_line = f"END (Job Ready {target} 🚀)"
    if not any(line.strip().lower().startswith("end") for line in lines):
        lines.extend(["  ↓", end_line])

    # Normalize arrow separators between nodes.
    normalized: list[str] = []
    for index, line in enumerate(lines):
        text = line.strip()
        normalized.append(text if text == "↓" else line)
        if index < len(lines) - 1 and text != "↓" and lines[index + 1].strip() != "↓":
            normalized.append("  ↓")

    if normalized[-1].strip() != end_line:
        normalized.append("  ↓")
        normalized.append(end_line)

    return "\n".join(normalized)


def _normalize_level(level: str) -> str | None:
    value = re.sub(r"\s+", " ", (level or "").strip().lower())
    if "begin" in value:
        return "Beginner"
    if "inter" in value:
        return "Intermediate"
    if "adv" in value:
        return "Advanced"
    if "expert" in value or "pro" in value:
        return "Expert"
    return None


def _clean_text(value: Any, *, max_len: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:-")
    if len(text) <= max_len:
        return text
    window = text[: max_len + 1]
    cut = window.rfind(" ")
    if cut >= int(max_len * 0.6):
        return window[:cut].strip(" ,;:-")
    return text[:max_len].strip(" ,;:-")
