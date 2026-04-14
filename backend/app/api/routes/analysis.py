from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.db import COLLECTIONS, get_db
from app.core.async_utils import run_blocking
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
    SkillRoadmapOut,
    SkillRoadmapRequest,
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
from app.services.document_parser import UnsupportedFileTypeError, extract_text
from app.services.skill_roadmap_service import build_missing_skill_details, build_skill_roadmap

router = APIRouter()


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
        jd_text = await run_blocking(extract_text, jd_file.filename or "jd_file", jd_bytes)
        resume_text = await run_blocking(extract_text, resume_file.filename or "resume_file", resume_bytes)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if len(jd_text.strip()) < 80:
        raise HTTPException(status_code=400, detail="JD text is too short for analysis")
    if len(resume_text.strip()) < 80:
        raise HTTPException(status_code=400, detail="Resume text is too short for analysis")

    practice_answer_items = parse_practice_answers(practice_answers)

    try:
        result = await run_blocking(
            analysis_engine.analyze_match,
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
    analysis_record_id, record_document = build_analysis_record_document(
        owner_id=current_user["_id"],
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

    generated = await run_blocking(
        analysis_engine.generate_hr_questions,
        jd_text=jd_text,
        resume_text=resume_text,
        count=6,
    )
    role_track = generated.get("role_track") or "General Professional Role"

    questions_out = normalize_hr_questions(generated.get("questions"))

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
        evaluated = await run_blocking(
            analysis_engine.evaluate_hr_answers,
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

    skill_details = await run_blocking(
        build_missing_skill_details,
        missing_skills=missing_skills,
        jd_text=jd_text,
        resume_text=resume_text,
    )

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
    try:
        roadmap = await run_blocking(build_skill_roadmap, target=payload.target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    analysis_record_id = payload.analysis_record_id
    if analysis_record_id:
        record = await db[COLLECTIONS["analysis_records"]].find_one(
            {"_id": analysis_record_id, "owner_id": current_user["_id"]}
        )
        if not record:
            raise HTTPException(status_code=404, detail="Analysis record not found")

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

    generated = await run_blocking(
        analysis_engine.generate_mcq_assessment,
        jd_text=jd_text,
        count=payload.question_count,
    )
    role_track = str(generated.get("role_track") or "General Professional Role")
    stored_questions, response_questions = prepare_mcq_questions(generated.get("questions"))

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
    results, correct_count, total_questions, score_percentage = evaluate_mcq_answers(
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

    generated = await run_blocking(
        analysis_engine.generate_resume_questions,
        resume_text=resume_text,
        jd_text=jd_text,
        count=payload.question_count,
    )
    role_track = str(generated.get("role_track") or "General Professional Role")
    stored_questions, response_questions = prepare_resume_questions(generated.get("questions"))

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

    answers_payload = build_resume_answers_payload(
        stored_questions=stored_questions,
        submitted_answers=payload.answers,
    )

    try:
        evaluated = await run_blocking(
            analysis_engine.evaluate_resume_answers,
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


