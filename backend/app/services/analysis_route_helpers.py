import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from fastapi import HTTPException

from app.models.api_schemas import HRPracticeQuestionOut, MCQAssessmentResultOut, ResumeAssessmentQuestionOut


async def parse_practice_answers(raw_value: str | None) -> list[dict[str, str]]:
    if not raw_value:
        return []

    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid practice answers payload") from exc

    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="Practice answers must be a JSON array")

    sanitized: list[dict[str, str]] = []
    for index, item in enumerate(payload[:8]):
        if not isinstance(item, dict):
            continue

        question = str(item.get("question", "")).strip()[:220]
        answer = str(item.get("answer", "")).strip()[:1500]
        if not answer:
            continue

        sanitized.append(
            {
                "question": question or f"Question {index + 1}",
                "answer": answer,
            }
        )

    return sanitized


async def build_analysis_record_document(
    *,
    owner_id: str,
    owner_email: str | None = None,
    jd_filename: str,
    resume_filename: str,
    jd_text: str,
    resume_text: str,
    practice_answers: list[dict[str, str]],
    result: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    analysis_record_id = str(uuid.uuid4())
    document = {
        "_id": analysis_record_id,
        "owner_id": owner_id,
        "owner_email": owner_email,
        "jd_filename": jd_filename,
        "resume_filename": resume_filename,
        "jd_content_hash": hashlib.sha256(jd_text.encode("utf-8")).hexdigest(),
        "resume_content_hash": hashlib.sha256(resume_text.encode("utf-8")).hexdigest(),
        "jd_text": jd_text[:20000],
        "resume_text": resume_text[:20000],
        "practice_answers": practice_answers,
        "result": result,
        "created_at": datetime.now(timezone.utc),
    }
    return analysis_record_id, document


async def normalize_hr_questions(raw_questions: Any) -> list[HRPracticeQuestionOut]:
    questions_out: list[HRPracticeQuestionOut] = []
    for index, item in enumerate(raw_questions or []):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        questions_out.append(
            HRPracticeQuestionOut(
                question_id=f"q{index + 1}",
                question=question,
                focus=str(item.get("focus") or "General fit"),
            )
        )
    return questions_out


async def prepare_mcq_questions(raw_questions: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stored_questions: list[dict[str, Any]] = []
    response_questions: list[dict[str, Any]] = []

    for index, item in enumerate(raw_questions or []):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        options = item.get("options") if isinstance(item.get("options"), list) else []
        cleaned_options = [str(option).strip() for option in options if str(option).strip()][:4]
        if not question or len(cleaned_options) != 4:
            continue

        try:
            correct_option_index = int(item.get("correct_option_index"))
        except (TypeError, ValueError):
            continue
        if correct_option_index < 0 or correct_option_index > 3:
            continue

        question_id = f"q{index + 1}"
        stored_questions.append(
            {
                "question_id": question_id,
                "question": question,
                "options": cleaned_options,
                "correct_option_index": correct_option_index,
            }
        )
        response_questions.append(
            {
                "question_id": question_id,
                "question": question,
                "options": cleaned_options,
            }
        )

    return stored_questions, response_questions


async def evaluate_mcq_answers(
    *,
    stored_questions: Sequence[dict[str, Any]],
    answer_map: dict[str, int],
) -> tuple[list[MCQAssessmentResultOut], int, int, int]:
    if len(answer_map) < len(stored_questions):
        raise HTTPException(status_code=400, detail="Please answer all assessment questions")

    results: list[MCQAssessmentResultOut] = []
    correct_count = 0
    for question in stored_questions:
        question_id = str(question.get("question_id") or "")
        if not question_id or question_id not in answer_map:
            raise HTTPException(status_code=400, detail="Please answer all assessment questions")

        options = [str(option).strip() for option in (question.get("options") or [])][:4]
        if len(options) != 4:
            continue

        selected_option_index = int(answer_map[question_id])
        correct_option_index = int(question.get("correct_option_index") or 0)
        selected_answer = options[selected_option_index]
        correct_answer = options[correct_option_index]
        is_correct = selected_option_index == correct_option_index
        if is_correct:
            correct_count += 1

        results.append(
            MCQAssessmentResultOut(
                question_id=question_id,
                question=str(question.get("question") or ""),
                selected_option_index=selected_option_index,
                selected_answer=selected_answer,
                is_correct=is_correct,
                correct_option_index=correct_option_index,
                correct_answer=correct_answer,
            )
        )

    total_questions = max(1, len(results))
    score_percentage = int(round((correct_count / total_questions) * 100))
    return results, correct_count, total_questions, score_percentage


async def prepare_resume_questions(raw_questions: Any) -> tuple[list[dict[str, Any]], list[ResumeAssessmentQuestionOut]]:
    stored_questions: list[dict[str, Any]] = []
    response_questions: list[ResumeAssessmentQuestionOut] = []

    for index, item in enumerate(raw_questions or []):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        focus = str(item.get("focus") or "Resume skill application").strip()
        if not question:
            continue

        question_id = f"q{index + 1}"
        stored_questions.append(
            {
                "question_id": question_id,
                "question": question,
                "focus": focus,
            }
        )
        response_questions.append(
            ResumeAssessmentQuestionOut(
                question_id=question_id,
                question=question,
                focus=focus,
            )
        )

    return stored_questions, response_questions


async def build_resume_answers_payload(
    *,
    stored_questions: Sequence[dict[str, Any]],
    submitted_answers: Sequence[Any],
) -> list[dict[str, str]]:
    answer_map = {item.question_id: item for item in submitted_answers}
    if len(answer_map) < len(stored_questions):
        raise HTTPException(status_code=400, detail="Please answer all resume assessment questions")

    answers_payload: list[dict[str, str]] = []
    for question in stored_questions:
        question_id = str(question.get("question_id") or "")
        if not question_id or question_id not in answer_map:
            raise HTTPException(status_code=400, detail="Please answer all resume assessment questions")

        submitted = answer_map[question_id]
        answer_text = str(submitted.answer or "").strip()
        if not answer_text:
            raise HTTPException(status_code=400, detail="Please answer all resume assessment questions")

        answers_payload.append(
            {
                "question_id": question_id,
                "question": str(question.get("question") or submitted.question or "").strip(),
                "answer": answer_text,
            }
        )

    return answers_payload
