from datetime import datetime, timezone
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.db import COLLECTIONS, get_db
from app.core.dependencies import get_current_user
from app.models.api_schemas import (
    AnalysisMatchOut,
    HRPracticeEvaluateOut,
    HRPracticeEvaluateRequest,
    HRPracticeQuestionOut,
    HRPracticeStartOut,
    HRPracticeStartRequest,
    MCQAssessmentEvaluateOut,
    MCQAssessmentEvaluateRequest,
    MCQAssessmentResultOut,
    MCQAssessmentStartOut,
    MCQAssessmentStartRequest,
    ResumeAssessmentEvaluateOut,
    ResumeAssessmentEvaluateRequest,
    ResumeAssessmentQuestionOut,
    ResumeAssessmentStartOut,
    ResumeUpgradeGenerateRequest,
    ResumeUpgradeOut,
    SkillRoadmapOut,
    SkillRoadmapRequest,
    SkillStepAssessmentEvaluateOut,
    SkillStepAssessmentEvaluateRequest,
    SkillStepAssessmentStartOut,
    SkillStepAssessmentStartRequest,
    SkillUpdateStartOut,
    SkillUpdateStartRequest,
)
from app.services.analysis_route_helpers import (
    build_analysis_record_document,
    build_resume_answers_payload,
    evaluate_mcq_answers,
    normalize_hr_questions,
    parse_practice_answers,
    prepare_mcq_questions,
    prepare_resume_questions,
)
from app.services.analysis_engine import analysis_engine
from app.services.document_parser import UnsupportedFileTypeError, extract_text_async
from app.services.jd_overview_service import extract_jd_identity
from app.services.skill_roadmap_service import (
    ROADMAP_VERSION,
    build_skill_roadmap,
    build_skill_step_assessment,
)

router = APIRouter()
_skill_step_assessment_sessions: dict[str, dict[str, Any]] = {}
_RESUME_UPGRADE_FORMAT_VERSION = 5


def _is_resume_upgrade_cache_healthy(cached_result: dict[str, Any] | None) -> bool:
    if not isinstance(cached_result, dict):
        return False

    ats_resume = str(cached_result.get("ats_resume") or "")
    if len(ats_resume.strip()) < 80:
        return False

    required_sections = [
        "PROFESSIONAL SUMMARY",
        "WORK EXPERIENCE",
        "PROJECTS",
        "EDUCATION",
        "SKILLS",
    ]
    if any(section not in ats_resume for section in required_sections):
        return False

    known_bad_patterns = [
        "{'institution':",
        "SUGGESTED SKILLS TO ADD",
        "Built architected",
        "\nExperience\n- Built",
    ]
    if any(pattern in ats_resume for pattern in known_bad_patterns):
        return False

    return True


def _quick_skill_details(missing_skills: list[str], reasons: list[str]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    reason_lines = [str(item or "").strip() for item in (reasons or []) if str(item or "").strip()]

    for skill in missing_skills:
        skill_name = str(skill or "").strip()
        if not skill_name:
            continue

        skill_lower = skill_name.lower()
        reason = next((line for line in reason_lines if skill_lower in line.lower()), "")
        why_missing = reason or f"Your resume has limited direct project evidence for {skill_name}."

        details.append(
            {
                "skill": skill_name,
                "why_missing": why_missing,
                "how_to_fix": [
                    f"Build one mini project using {skill_name} and publish it on GitHub.",
                    f"Add 2 resume bullets with measurable impact for {skill_name}.",
                    f"Practice interview questions for {skill_name} with practical examples.",
                ],
            }
        )

    return details


@router.post("/match", response_model=AnalysisMatchOut)
async def analyze_resume_match(
    jd_file: UploadFile = File(...),
    resume_file: UploadFile = File(...),
    practice_answers: str | None = Form(None),
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> AnalysisMatchOut:
    jd_bytes = await jd_file.read()
    resume_bytes = await resume_file.read()

    try:
        jd_text = await extract_text_async(jd_file.filename or "jd_file", jd_bytes)
        resume_text = await extract_text_async(resume_file.filename or "resume_file", resume_bytes)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if len(jd_text.strip()) < 80:
        raise HTTPException(status_code=400, detail="JD text is too short for analysis")
    if len(resume_text.strip()) < 80:
        raise HTTPException(status_code=400, detail="Resume text is too short for analysis")

    practice_answer_items = await parse_practice_answers(practice_answers)

    try:
        result = await analysis_engine.analyze_match_async(
            jd_text=jd_text,
            resume_text=resume_text,
            practice_answers=practice_answer_items,
        )
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 503 if "not configured" in detail.lower() else 502
        raise HTTPException(status_code=status_code, detail=detail) from exc

    jd_filename = jd_file.filename or "job_description"
    resume_filename = resume_file.filename or "resume"
    jd_identity = await extract_jd_identity(jd_text, filename=jd_filename)
    analysis_record_id, record_document = await build_analysis_record_document(
        owner_id=current_user["_id"],
        owner_email=str(current_user.get("email") or "").strip().lower() or None,
        jd_filename=jd_filename,
        resume_filename=resume_filename,
        jd_text=jd_text,
        resume_text=resume_text,
        practice_answers=practice_answer_items,
        result=result,
    )

    await db[COLLECTIONS["analysis_records"]].insert_one(record_document)

    return AnalysisMatchOut(
        analysis_record_id=analysis_record_id,
        jd_filename=jd_filename,
        resume_filename=resume_filename,
        company_name=jd_identity.get("company_name", ""),
        role_title=jd_identity.get("role_title", ""),
        **result,
    )


@router.post("/hr-practice/start", response_model=HRPracticeStartOut)
async def start_hr_practice(
    payload: HRPracticeStartRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> HRPracticeStartOut:
    record = await db[COLLECTIONS["analysis_records"]].find_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Analysis record not found")

    jd_text = str(record.get("jd_text") or "")
    resume_text = str(record.get("resume_text") or "")
    if len(jd_text.strip()) < 80 or len(resume_text.strip()) < 80:
        raise HTTPException(status_code=400, detail="Analysis record is missing JD/Resume text")

    generated = await analysis_engine.generate_hr_questions_async(
        jd_text=jd_text,
        resume_text=resume_text,
        count=6,
    )
    role_track = generated.get("role_track") or "General Professional Role"

    questions_out = await normalize_hr_questions(generated.get("questions"))

    if not questions_out:
        raise HTTPException(status_code=502, detail="Could not generate HR practice questions")

    await db[COLLECTIONS["analysis_records"]].update_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]},
        {
            "$set": {
                "hr_practice.role_track": role_track,
                "hr_practice.questions": [item.model_dump() for item in questions_out],
                "hr_practice.generated_at": datetime.now(timezone.utc),
            }
        },
    )

    return HRPracticeStartOut(
        analysis_record_id=payload.analysis_record_id,
        role_track=role_track,
        questions=questions_out,
    )


@router.post("/hr-practice/evaluate", response_model=HRPracticeEvaluateOut)
async def evaluate_hr_practice(
    payload: HRPracticeEvaluateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> HRPracticeEvaluateOut:
    record = await db[COLLECTIONS["analysis_records"]].find_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Analysis record not found")

    jd_text = str(record.get("jd_text") or "")
    resume_text = str(record.get("resume_text") or "")

    answers_payload = [
        {
            "question_id": item.question_id,
            "question": item.question,
            "answer": item.answer,
        }
        for item in payload.answers
    ]

    try:
        evaluated = await analysis_engine.evaluate_hr_answers_async(
            jd_text=jd_text,
            resume_text=resume_text,
            answers=answers_payload,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db[COLLECTIONS["analysis_records"]].update_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]},
        {
            "$set": {
                "hr_practice.last_answers": answers_payload,
                "hr_practice.last_evaluation": evaluated,
                "hr_practice.evaluated_at": datetime.now(timezone.utc),
            }
        },
    )

    return HRPracticeEvaluateOut(
        analysis_record_id=payload.analysis_record_id,
        role_track=str(evaluated.get("role_track") or "General Professional Role"),
        overall_score=int(evaluated.get("overall_score") or 0),
        verdict=str(evaluated.get("verdict") or "Needs Improvement"),
        answer_feedback=list(evaluated.get("answer_feedback") or []),
        final_tips=list(evaluated.get("final_tips") or []),
        uses_llm=bool(evaluated.get("uses_llm") or False),
    )


@router.post("/skill-update/start", response_model=SkillUpdateStartOut)
async def start_skill_update(
    payload: SkillUpdateStartRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> SkillUpdateStartOut:
    record = await db[COLLECTIONS["analysis_records"]].find_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Analysis record not found")

    existing_skill_update = record.get("skill_update") if isinstance(record.get("skill_update"), dict) else {}
    existing_missing = [
        str(item).strip()
        for item in (existing_skill_update.get("missing_skills") or [])
        if str(item).strip()
    ]
    existing_details = [
        item
        for item in (existing_skill_update.get("skill_details") or [])
        if isinstance(item, dict) and str(item.get("skill") or "").strip()
    ]

    result = record.get("result") or {}
    missing_skills = [str(item).strip() for item in (result.get("missing_skills") or []) if str(item).strip()]
    if not missing_skills:
        missing_skills = [
            str(item).strip()
            for item in (result.get("critical_missing_skills") or result.get("missing_keywords") or [])
            if str(item).strip()
        ]

    jd_text = str(record.get("jd_text") or "")
    resume_text = str(record.get("resume_text") or "")
    suggested_roles = list((result or {}).get("suggested_roles") or [])
    role_track = str(suggested_roles[0]).strip() if suggested_roles else "General Professional Role"

    if existing_missing and existing_details:
        return SkillUpdateStartOut(
            analysis_record_id=payload.analysis_record_id,
            role_track=role_track,
            missing_skills=existing_missing,
            skill_details=existing_details,
        )

    skill_details = _quick_skill_details(missing_skills, list((result or {}).get("low_match_reasons") or []))

    await db[COLLECTIONS["analysis_records"]].update_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]},
        {
            "$set": {
                "skill_update.missing_skills": missing_skills,
                "skill_update.skill_details": skill_details,
                "skill_update.generated_at": datetime.now(timezone.utc),
            }
        },
    )

    return SkillUpdateStartOut(
        analysis_record_id=payload.analysis_record_id,
        role_track=role_track,
        missing_skills=missing_skills,
        skill_details=skill_details,
    )


@router.post("/skill-update/roadmap", response_model=SkillRoadmapOut)
async def generate_skill_roadmap(
    payload: SkillRoadmapRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> SkillRoadmapOut:
    normalized_target = str(payload.target or "").strip().lower()
    if not normalized_target:
        raise HTTPException(status_code=400, detail="Please provide a skill or role target")

    analysis_record_id = payload.analysis_record_id
    record = None
    if analysis_record_id:
        record = await db[COLLECTIONS["analysis_records"]].find_one(
            {"_id": analysis_record_id, "owner_id": current_user["_id"]}
        )
        if not record:
            raise HTTPException(status_code=404, detail="Analysis record not found")

        skill_update = record.get("skill_update") if isinstance(record.get("skill_update"), dict) else {}
        cached_target = str(skill_update.get("last_target") or "").strip().lower()
        cached_roadmap = skill_update.get("last_roadmap") if isinstance(skill_update.get("last_roadmap"), dict) else None
        try:
            cached_version = int((cached_roadmap or {}).get("roadmap_version") or 1)
        except (TypeError, ValueError):
            cached_version = 1

        if cached_roadmap and cached_target == normalized_target and cached_version >= ROADMAP_VERSION:
            return SkillRoadmapOut(
                analysis_record_id=analysis_record_id,
                target=str(cached_roadmap.get("target") or payload.target),
                overview=str(cached_roadmap.get("overview") or ""),
                roadmap_steps=list(cached_roadmap.get("roadmap_steps") or []),
                detailed_plan=list(cached_roadmap.get("detailed_plan") or []),
                flowchart_text=str(cached_roadmap.get("flowchart_text") or ""),
                projects=list(cached_roadmap.get("projects") or []),
                resources=list(cached_roadmap.get("resources") or []),
                generated_by=str(cached_roadmap.get("generated_by") or "cached"),
            )

    try:
        roadmap = await build_skill_roadmap(target=payload.target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if analysis_record_id:
        await db[COLLECTIONS["analysis_records"]].update_one(
            {"_id": analysis_record_id, "owner_id": current_user["_id"]},
            {
                "$set": {
                    "skill_update.last_target": payload.target,
                    "skill_update.last_roadmap": roadmap,
                    "skill_update.roadmap_generated_at": datetime.now(timezone.utc),
                }
            },
        )

    return SkillRoadmapOut(
        analysis_record_id=analysis_record_id,
        target=str(roadmap.get("target") or payload.target),
        overview=str(roadmap.get("overview") or ""),
        roadmap_steps=list(roadmap.get("roadmap_steps") or []),
        detailed_plan=list(roadmap.get("detailed_plan") or []),
        flowchart_text=str(roadmap.get("flowchart_text") or ""),
        projects=list(roadmap.get("projects") or []),
        resources=list(roadmap.get("resources") or []),
        generated_by=str(roadmap.get("generated_by") or "fallback"),
    )


@router.post("/skill-update/step-assessment/start", response_model=SkillStepAssessmentStartOut)
async def start_skill_step_assessment(
    payload: SkillStepAssessmentStartRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> SkillStepAssessmentStartOut:
    analysis_record_id = payload.analysis_record_id

    if analysis_record_id:
        record = await db[COLLECTIONS["analysis_records"]].find_one(
            {"_id": analysis_record_id, "owner_id": current_user["_id"]}
        )
        if not record:
            raise HTTPException(status_code=404, detail="Analysis record not found")

    try:
        generated = await build_skill_step_assessment(
            target=payload.target,
            step_title=payload.step_title,
            step_description=payload.step_description,
            action_items=list(payload.action_items or []),
            question_count=payload.question_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stored_questions = list(generated.get("questions") or [])
    response_questions = [
        {
            "question_id": str(item.get("question_id") or f"sq{index + 1}"),
            "question": str(item.get("question") or ""),
            "options": list(item.get("options") or []),
        }
        for index, item in enumerate(stored_questions)
        if str(item.get("question") or "").strip() and isinstance(item.get("options"), list) and len(item.get("options")) == 4
    ]
    if not response_questions:
        raise HTTPException(status_code=502, detail="Could not generate step assessment questions")

    session_id = str(uuid.uuid4())
    _skill_step_assessment_sessions[session_id] = {
        "owner_id": current_user["_id"],
        "analysis_record_id": analysis_record_id,
        "target": str(generated.get("target") or payload.target),
        "step_title": str(generated.get("step_title") or payload.step_title),
        "pass_threshold": int(generated.get("pass_threshold") or 60),
        "questions": stored_questions,
        "created_at": datetime.now(timezone.utc),
    }

    if analysis_record_id:
        await db[COLLECTIONS["analysis_records"]].update_one(
            {"_id": analysis_record_id, "owner_id": current_user["_id"]},
            {
                "$set": {
                    "skill_update.last_step_assessment": {
                        "session_id": session_id,
                        "target": str(generated.get("target") or payload.target),
                        "step_title": str(generated.get("step_title") or payload.step_title),
                        "generated_at": datetime.now(timezone.utc),
                    }
                }
            },
        )

    return SkillStepAssessmentStartOut(
        session_id=session_id,
        analysis_record_id=analysis_record_id,
        target=str(generated.get("target") or payload.target),
        step_title=str(generated.get("step_title") or payload.step_title),
        learning_content=str(generated.get("learning_content") or ""),
        key_points=list(generated.get("key_points") or []),
        pass_threshold=int(generated.get("pass_threshold") or 60),
        total_questions=len(response_questions),
        questions=response_questions,
        generated_by=str(generated.get("generated_by") or "fallback"),
    )


@router.post("/skill-update/step-assessment/evaluate", response_model=SkillStepAssessmentEvaluateOut)
async def evaluate_skill_step_assessment(
    payload: SkillStepAssessmentEvaluateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> SkillStepAssessmentEvaluateOut:
    session = _skill_step_assessment_sessions.get(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Assessment session not found or expired")

    if session.get("owner_id") != current_user["_id"]:
        raise HTTPException(status_code=403, detail="You cannot access this assessment session")

    answer_map: dict[str, int] = {}
    for item in payload.answers:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id") or "").strip()
        try:
            selected_index = int(item.get("selected_option_index"))
        except (TypeError, ValueError):
            continue
        if not question_id or selected_index < 0 or selected_index > 3:
            continue
        answer_map[question_id] = selected_index

    stored_questions = list(session.get("questions") or [])
    results: list[dict[str, Any]] = []
    correct_count = 0
    for question in stored_questions:
        question_id = str(question.get("question_id") or "").strip()
        question_text = str(question.get("question") or "").strip()
        options = [str(option).strip() for option in list(question.get("options") or [])][:4]
        if not question_id or len(options) != 4:
            continue

        correct_option_index = int(question.get("correct_option_index") or 0)
        selected_option_index = answer_map.get(question_id)
        is_answered = isinstance(selected_option_index, int) and 0 <= selected_option_index <= 3
        is_correct = is_answered and selected_option_index == correct_option_index
        if is_correct:
            correct_count += 1

        results.append(
            {
                "question_id": question_id,
                "question": question_text,
                "selected_option_index": selected_option_index if is_answered else -1,
                "selected_answer": options[selected_option_index] if is_answered else "Skipped",
                "is_correct": bool(is_correct),
                "correct_option_index": correct_option_index,
                "correct_answer": options[correct_option_index],
            }
        )

    total_questions = max(1, len(results))
    score_percentage = int(round((correct_count / total_questions) * 100))

    pass_threshold = int(session.get("pass_threshold") or 60)
    passed = score_percentage >= pass_threshold
    motivation = (
        "Great progress. You cleared this step and unlocked the next roadmap stage."
        if passed
        else "Good effort. Review the key points once more and retry to unlock the next step."
    )

    analysis_record_id = session.get("analysis_record_id")
    if analysis_record_id:
        await db[COLLECTIONS["analysis_records"]].update_one(
            {"_id": analysis_record_id, "owner_id": current_user["_id"]},
            {
                "$set": {
                    "skill_update.last_step_assessment_result": {
                        "session_id": payload.session_id,
                        "step_title": session.get("step_title") or "",
                        "target": session.get("target") or "",
                        "submitted_answers": list(payload.answers or []),
                        "results": results,
                        "total_questions": total_questions,
                        "correct_count": correct_count,
                        "score_percentage": score_percentage,
                        "pass_threshold": pass_threshold,
                        "passed": passed,
                        "evaluated_at": datetime.now(timezone.utc),
                    }
                }
            },
        )

    return SkillStepAssessmentEvaluateOut(
        session_id=payload.session_id,
        total_questions=total_questions,
        correct_count=correct_count,
        score_percentage=score_percentage,
        pass_threshold=pass_threshold,
        passed=passed,
        motivation=motivation,
        results=results,
    )


@router.post("/resume-upgrade/generate", response_model=ResumeUpgradeOut)
async def generate_resume_upgrade(
    payload: ResumeUpgradeGenerateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> ResumeUpgradeOut:
    record = await db[COLLECTIONS["analysis_records"]].find_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Analysis record not found")

    resume_text = str(record.get("resume_text") or "")
    jd_text = str(record.get("jd_text") or "")
    if len(resume_text.strip()) < 80:
        raise HTTPException(status_code=400, detail="Analysis record is missing resume text")
    if len(jd_text.strip()) < 80:
        raise HTTPException(status_code=400, detail="Analysis record is missing JD text")

    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    missing_skills = [
        str(item).strip()
        for item in (
            result.get("missing_skills")
            or result.get("critical_missing_skills")
            or result.get("missing_keywords")
            or []
        )
        if str(item).strip()
    ]
    suggested_roles = [
        str(item).strip() for item in (result.get("suggested_roles") or []) if str(item).strip()
    ]
    target_role = suggested_roles[0] if suggested_roles else "Target Role"
    custom_prompt = str(payload.custom_prompt or "").strip()

    resume_upgrade = record.get("resume_upgrade") if isinstance(record.get("resume_upgrade"), dict) else {}
    cached_result = resume_upgrade.get("last_result") if isinstance(resume_upgrade.get("last_result"), dict) else None
    cached_prompt = str(resume_upgrade.get("last_prompt") or "").strip()
    try:
        cached_format_version = int(resume_upgrade.get("format_version") or 1)
    except (TypeError, ValueError):
        cached_format_version = 1

    if (
        cached_result
        and cached_prompt == custom_prompt
        and cached_format_version >= _RESUME_UPGRADE_FORMAT_VERSION
        and _is_resume_upgrade_cache_healthy(cached_result)
    ):
        return ResumeUpgradeOut(
            analysis_record_id=payload.analysis_record_id,
            target_role=str(cached_result.get("target_role") or target_role),
            ats_resume=str(cached_result.get("ats_resume") or ""),
            missing_skills_considered=list(cached_result.get("missing_skills_considered") or missing_skills),
            missing_skills_added=list(cached_result.get("missing_skills_added") or []),
            improvement_notes=list(cached_result.get("improvement_notes") or []),
            uses_llm=bool(cached_result.get("uses_llm") or False),
        )

    generated = await analysis_engine.generate_ats_resume_async(
        jd_text=jd_text,
        resume_text=resume_text,
        missing_skills=missing_skills,
        target_role=target_role,
        custom_prompt=custom_prompt,
    )

    await db[COLLECTIONS["analysis_records"]].update_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]},
        {
            "$set": {
                "resume_upgrade.last_result": generated,
                "resume_upgrade.last_prompt": custom_prompt,
                "resume_upgrade.format_version": _RESUME_UPGRADE_FORMAT_VERSION,
                "resume_upgrade.generated_at": datetime.now(timezone.utc),
            }
        },
    )

    return ResumeUpgradeOut(
        analysis_record_id=payload.analysis_record_id,
        target_role=str(generated.get("target_role") or target_role),
        ats_resume=str(generated.get("ats_resume") or ""),
        missing_skills_considered=list(generated.get("missing_skills_considered") or missing_skills),
        missing_skills_added=list(generated.get("missing_skills_added") or []),
        improvement_notes=list(generated.get("improvement_notes") or []),
        uses_llm=bool(generated.get("uses_llm") or False),
    )


@router.post("/mcq-assessment/start", response_model=MCQAssessmentStartOut)
async def start_mcq_assessment(
    payload: MCQAssessmentStartRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> MCQAssessmentStartOut:
    record = await db[COLLECTIONS["analysis_records"]].find_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Analysis record not found")

    jd_text = str(record.get("jd_text") or "")
    if len(jd_text.strip()) < 80:
        raise HTTPException(status_code=400, detail="Analysis record is missing JD text")

    generated = await analysis_engine.generate_mcq_assessment_async(
        jd_text=jd_text,
        count=payload.question_count,
    )
    role_track = str(generated.get("role_track") or "General Professional Role")
    stored_questions, response_questions = await prepare_mcq_questions(generated.get("questions"))

    if not stored_questions:
        raise HTTPException(status_code=502, detail="Could not generate MCQ assessment from JD")

    await db[COLLECTIONS["analysis_records"]].update_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]},
        {
            "$set": {
                "mcq_assessment.questions": stored_questions,
                "mcq_assessment.role_track": role_track,
                "mcq_assessment.total_questions": len(stored_questions),
                "mcq_assessment.generated_at": datetime.now(timezone.utc),
            }
        },
    )

    return MCQAssessmentStartOut(
        analysis_record_id=payload.analysis_record_id,
        role_track=role_track,
        total_questions=len(response_questions),
        questions=response_questions,
    )


@router.post("/mcq-assessment/evaluate", response_model=MCQAssessmentEvaluateOut)
async def evaluate_mcq_assessment(
    payload: MCQAssessmentEvaluateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> MCQAssessmentEvaluateOut:
    record = await db[COLLECTIONS["analysis_records"]].find_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Analysis record not found")

    stored_questions = list(((record.get("mcq_assessment") or {}).get("questions") or []))
    if not stored_questions:
        raise HTTPException(status_code=400, detail="MCQ assessment not started for this analysis record")

    answer_map = {item.question_id: item.selected_option_index for item in payload.answers}
    results, correct_count, total_questions, score_percentage = await evaluate_mcq_answers(
        stored_questions=stored_questions,
        answer_map=answer_map,
    )

    await db[COLLECTIONS["analysis_records"]].update_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]},
        {
            "$set": {
                "mcq_assessment.last_answers": [
                    {"question_id": item.question_id, "selected_option_index": item.selected_option_index}
                    for item in payload.answers
                ],
                "mcq_assessment.last_result": {
                    "total_questions": total_questions,
                    "correct_count": correct_count,
                    "score_percentage": score_percentage,
                    "results": [item.model_dump() for item in results],
                },
                "mcq_assessment.evaluated_at": datetime.now(timezone.utc),
            }
        },
    )

    return MCQAssessmentEvaluateOut(
        analysis_record_id=payload.analysis_record_id,
        total_questions=total_questions,
        correct_count=correct_count,
        score_percentage=score_percentage,
        results=results,
    )


@router.post("/resume-assessment/start", response_model=ResumeAssessmentStartOut)
async def start_resume_assessment(
    payload: MCQAssessmentStartRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> ResumeAssessmentStartOut:
    record = await db[COLLECTIONS["analysis_records"]].find_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Analysis record not found")

    resume_text = str(record.get("resume_text") or "")
    jd_text = str(record.get("jd_text") or "")
    if len(resume_text.strip()) < 80:
        raise HTTPException(status_code=400, detail="Analysis record is missing resume text")

    generated = await analysis_engine.generate_resume_questions_async(
        resume_text=resume_text,
        jd_text=jd_text,
        count=payload.question_count,
    )
    role_track = str(generated.get("role_track") or "General Professional Role")
    stored_questions, response_questions = await prepare_resume_questions(generated.get("questions"))

    if not stored_questions:
        raise HTTPException(status_code=502, detail="Could not generate resume assessment questions")

    await db[COLLECTIONS["analysis_records"]].update_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]},
        {
            "$set": {
                "resume_assessment.questions": stored_questions,
                "resume_assessment.role_track": role_track,
                "resume_assessment.total_questions": len(stored_questions),
                "resume_assessment.generated_at": datetime.now(timezone.utc),
            }
        },
    )

    return ResumeAssessmentStartOut(
        analysis_record_id=payload.analysis_record_id,
        role_track=role_track,
        total_questions=len(response_questions),
        questions=response_questions,
    )


@router.post("/resume-assessment/evaluate", response_model=ResumeAssessmentEvaluateOut)
async def evaluate_resume_assessment(
    payload: ResumeAssessmentEvaluateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> ResumeAssessmentEvaluateOut:
    record = await db[COLLECTIONS["analysis_records"]].find_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Analysis record not found")

    stored_questions = list(((record.get("resume_assessment") or {}).get("questions") or []))
    if not stored_questions:
        raise HTTPException(status_code=400, detail="Resume assessment not started for this analysis record")

    answers_payload = await build_resume_answers_payload(
        stored_questions=stored_questions,
        submitted_answers=payload.answers,
    )

    try:
        evaluated = await analysis_engine.evaluate_resume_answers_async(
            jd_text=str(record.get("jd_text") or ""),
            resume_text=str(record.get("resume_text") or ""),
            answers=answers_payload,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db[COLLECTIONS["analysis_records"]].update_one(
        {"_id": payload.analysis_record_id, "owner_id": current_user["_id"]},
        {
            "$set": {
                "resume_assessment.last_answers": answers_payload,
                "resume_assessment.last_evaluation": evaluated,
                "resume_assessment.evaluated_at": datetime.now(timezone.utc),
            }
        },
    )

    return ResumeAssessmentEvaluateOut(
        analysis_record_id=payload.analysis_record_id,
        role_track=str(evaluated.get("role_track") or "Resume Skill Assessment"),
        overall_score=int(evaluated.get("overall_score") or 0),
        verdict=str(evaluated.get("verdict") or "Needs Improvement"),
        answer_feedback=list(evaluated.get("answer_feedback") or []),
        final_tips=list(evaluated.get("final_tips") or []),
        uses_llm=bool(evaluated.get("uses_llm") or False),
    )


