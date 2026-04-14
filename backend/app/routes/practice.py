import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.db import COLLECTIONS, get_db
from app.core.dependencies import get_current_user
from app.models.api_schemas import (
    AnswerSubmitOut,
    AnswerSubmitRequest,
    PracticeSessionOut,
    PracticeStartRequest,
    QuestionOut,
)
from app.services.difficulty_controller import adjust_difficulty
from app.services.evaluation_engine import evaluation_engine
from app.services.practice_route_helpers import generate_and_store_question_attempt, utcnow
from app.services.question_engine import question_engine

router = APIRouter()


def _clean_unique_strings(items: list[Any], *, max_items: int) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
        if len(cleaned) >= max_items:
            break
    return cleaned


def _is_non_skill_requirement(text: str) -> bool:
    lowered = str(text or "").lower()
    blocked_tokens = (
        "bond",
        "security amount",
        "salary",
        "ctc",
        "lpa",
        "stipend",
        "notice period",
        "working days",
        "shift",
        "per month",
        "per annum",
        "gross",
        "marks",
        "percentage",
        "cgpa",
        "board exam",
        "graduation",
        "batch",
        "eligibility",
    )
    return any(token in lowered for token in blocked_tokens)


@router.post("/start", response_model=PracticeSessionOut)
async def start_practice(
    payload: PracticeStartRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> PracticeSessionOut:
    documents = db[COLLECTIONS["documents"]]
    sessions = db[COLLECTIONS["practice_sessions"]]
    analysis_records = db[COLLECTIONS["analysis_records"]]

    document = await documents.find_one({"_id": str(payload.document_id), "owner_id": current_user["_id"]})
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    jd_overview = document.get("jd_overview") if isinstance(document.get("jd_overview"), dict) else {}
    title_lower = str(document.get("title") or "").lower()
    input_type = str(payload.input_type or "").strip().lower()
    if input_type not in {"jd", "resume"}:
        input_type = "resume" if any(token in title_lower for token in ("resume", "cv", "profile")) else "jd"
    role_title = str(jd_overview.get("role_title") or "").strip()
    required_skills = _clean_unique_strings(list(jd_overview.get("required_skills") or []), max_items=16)
    key_requirements = _clean_unique_strings(list(jd_overview.get("key_requirements") or []), max_items=10)
    key_requirements = [item for item in key_requirements if not _is_non_skill_requirement(item)]
    resume_skills: list[str] = []
    missing_skills: list[str] = []
    resume_text = (payload.resume_text or "").strip()

    matched_record: dict[str, Any] | None = None
    if payload.analysis_record_id:
        matched_record = await analysis_records.find_one({"_id": payload.analysis_record_id, "owner_id": current_user["_id"]})
        if not matched_record:
            raise HTTPException(status_code=404, detail="Analysis record not found")
    else:
        content_hash = str(document.get("content_hash") or "").strip()
        if content_hash:
            matched_record = await analysis_records.find_one(
                {"owner_id": current_user["_id"], "jd_content_hash": content_hash}
            )

    if matched_record:
        record_resume = str(matched_record.get("resume_text") or "").strip()
        if record_resume:
            resume_text = record_resume

        result = matched_record.get("result") if isinstance(matched_record.get("result"), dict) else {}
        role_title = str(result.get("role_title") or role_title).strip()

        analysis_required = list(result.get("missing_skills") or []) + list(result.get("matched_skills") or [])
        if analysis_required:
            required_skills = _clean_unique_strings([*required_skills, *analysis_required], max_items=18)

        analysis_requirements = list(result.get("jd_key_points") or [])
        if analysis_requirements:
            key_requirements = _clean_unique_strings([*key_requirements, *analysis_requirements], max_items=12)
            key_requirements = [item for item in key_requirements if not _is_non_skill_requirement(item)]

        resume_skill_candidates = (
            list(result.get("resume_role_keywords") or [])
            + list(result.get("matched_skills") or [])
            + list(result.get("matched_keywords") or [])
        )
        resume_skills = _clean_unique_strings(resume_skill_candidates, max_items=16)
        missing_skills = _clean_unique_strings(list(result.get("missing_skills") or []), max_items=16)

    if not required_skills:
        raw_text = str(document.get("raw_text") or "")
        extracted = question_engine.extract_skill_hints_from_text(raw_text, max_items=16)
        if extracted:
            required_skills = _clean_unique_strings(extracted, max_items=16)

    session_id = str(uuid.uuid4())
    session = {
        "_id": session_id,
        "document_id": document["_id"],
        "owner_id": current_user["_id"],
        "owner_email": str(current_user.get("email") or "").strip().lower() or None,
        "current_difficulty": 1,
        "score": 0.0,
        "total_answered": 0,
        "role_title": role_title,
        "required_skills": required_skills,
        "key_requirements": key_requirements,
        "resume_skills": resume_skills,
        "missing_skills": missing_skills,
        "input_type": input_type,
        "analysis_record_id": str(matched_record.get("_id") or payload.analysis_record_id or "") if matched_record or payload.analysis_record_id else "",
        "resume_text": resume_text,
        "created_at": await utcnow(),
    }
    await sessions.insert_one(session)

    return PracticeSessionOut(
        session_id=session_id,
        document_id=document["_id"],
        difficulty=1,
    )


@router.get("/{session_id}/question", response_model=QuestionOut)
async def get_question(
    session_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> QuestionOut:
    sessions = db[COLLECTIONS["practice_sessions"]]

    session = await sessions.find_one({"_id": str(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Practice session not found")
    attempt_id, question_text, difficulty = await generate_and_store_question_attempt(
        db=db,
        session=session,
        owner_id=current_user["_id"],
        owner_email=str(current_user.get("email") or "").strip().lower() or None,
    )

    return QuestionOut(
        question_id=attempt_id,
        question_text=question_text,
        difficulty=difficulty,
    )


@router.post("/answer", response_model=AnswerSubmitOut)
async def submit_answer(
    payload: AnswerSubmitRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> AnswerSubmitOut:
    sessions = db[COLLECTIONS["practice_sessions"]]
    documents = db[COLLECTIONS["documents"]]
    attempts_collection = db[COLLECTIONS["question_attempts"]]

    session = await sessions.find_one({"_id": str(payload.session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Practice session not found")

    document = await documents.find_one({"_id": session["document_id"]})
    if not document or document.get("owner_id") != current_user["_id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    attempt = await attempts_collection.find_one({"_id": str(payload.question_id)})
    if not attempt or attempt.get("session_id") != session["_id"]:
        raise HTTPException(status_code=404, detail="Question attempt not found")
    if attempt.get("user_answer") is not None:
        raise HTTPException(status_code=409, detail="This question was already answered")

    is_correct, feedback = await evaluation_engine.evaluate(
        expected_answer=attempt["expected_answer"],
        user_answer=payload.answer,
    )

    updated_difficulty = await adjust_difficulty(int(session.get("current_difficulty", 1)), is_correct)

    await attempts_collection.update_one(
        {"_id": attempt["_id"]},
        {"$set": {"user_answer": payload.answer, "is_correct": is_correct}},
    )

    increment = {"total_answered": 1}
    if is_correct:
        increment["score"] = 1.0

    await sessions.update_one(
        {"_id": session["_id"]},
        {
            "$inc": increment,
            "$set": {"current_difficulty": updated_difficulty},
        },
    )

    return AnswerSubmitOut(
        is_correct=is_correct,
        feedback=feedback,
        updated_difficulty=updated_difficulty,
        reference_answer=attempt["expected_answer"],
    )


