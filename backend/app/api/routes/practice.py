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

router = APIRouter()


@router.post("/start", response_model=PracticeSessionOut)
async def start_practice(
    payload: PracticeStartRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> PracticeSessionOut:
    documents = db[COLLECTIONS["documents"]]
    sessions = db[COLLECTIONS["practice_sessions"]]

    document = await documents.find_one({"_id": str(payload.document_id), "owner_id": current_user["_id"]})
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    session_id = str(uuid.uuid4())
    session = {
        "_id": session_id,
        "document_id": document["_id"],
        "current_difficulty": 1,
        "score": 0.0,
        "total_answered": 0,
        "created_at": utcnow(),
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

    is_correct, feedback = evaluation_engine.evaluate(
        expected_answer=attempt["expected_answer"],
        user_answer=payload.answer,
    )

    updated_difficulty = adjust_difficulty(int(session.get("current_difficulty", 1)), is_correct)

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


