import uuid
from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.db import COLLECTIONS
from app.services.question_engine import question_engine
from app.services.retrieval_service import pick_chunk_for_session_async


async def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def as_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def best_effort_question_pair(question_text: str, answer_text: str, fallback_text: str) -> tuple[str, str]:
    question = (question_text or "").strip()
    answer = (answer_text or "").strip()

    if not question or len(question.split()) < 3:
        question = "What is one key concept from this section?"
    elif not question.endswith("?"):
        question = f"{question.rstrip('.:!')}?"

    if not answer:
        sentence = (fallback_text or "").split(".", 1)[0].strip()
        answer = sentence or "Refer to the document section for the answer."

    return question, answer


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
    if any(token in lowered for token in blocked_tokens):
        return True
    if re.search(r"\b\d+\s*(?:month|months|year|years|lakh|lakhs|rs|inr)\b", lowered):
        return True
    return False


async def generate_and_store_question_attempt(
    *,
    db: AsyncIOMotorDatabase,
    session: dict[str, Any],
    owner_id: str,
    owner_email: str | None = None,
) -> tuple[str, str, int]:
    sessions = db[COLLECTIONS["practice_sessions"]]
    documents = db[COLLECTIONS["documents"]]
    attempts_collection = db[COLLECTIONS["question_attempts"]]

    document = await documents.find_one({"_id": session["document_id"]})
    if not document or document.get("owner_id") != owner_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    attempts = await attempts_collection.find({"session_id": session["_id"]}).sort("created_at", 1).to_list(length=None)

    related_rows = await documents.find(
        {"owner_id": owner_id, "content_hash": document["content_hash"]},
        {"_id": 1},
    ).to_list(length=None)
    related_document_ids = [row["_id"] for row in related_rows]
    historical_rows = await sessions.find(
        {"document_id": {"$in": related_document_ids}, "_id": {"$ne": session["_id"]}},
        {"_id": 1},
    ).sort("created_at", -1).limit(60).to_list(length=60)
    historical_session_ids = [row["_id"] for row in historical_rows]
    historical_attempts = (
        await attempts_collection.find({"session_id": {"$in": historical_session_ids}})
        .sort("created_at", -1)
        .limit(60)
        .to_list(length=60)
        if historical_session_ids
        else []
    )

    combined_attempts = [*historical_attempts, *attempts]
    usage_counts: Counter[uuid.UUID] = Counter()
    for attempt in combined_attempts:
        chunk_uuid = await as_uuid(attempt.get("source_chunk_id"))
        if chunk_uuid:
            usage_counts[chunk_uuid] += 1

    recent_chunk_ids: list[uuid.UUID] = []
    for attempt in attempts[-3:]:
        chunk_uuid = await as_uuid(attempt.get("source_chunk_id"))
        if chunk_uuid:
            recent_chunk_ids.append(chunk_uuid)

    if len(recent_chunk_ids) < 3:
        needed = 3 - len(recent_chunk_ids)
        historical_ids: list[uuid.UUID] = []
        for attempt in historical_attempts[: needed * 2]:
            chunk_uuid = await as_uuid(attempt.get("source_chunk_id"))
            if chunk_uuid:
                historical_ids.append(chunk_uuid)
        recent_chunk_ids.extend(historical_ids[:needed])

    recent_questions = [attempt.get("question_text", "") for attempt in historical_attempts if attempt.get("question_text")]
    recent_questions.extend([attempt.get("question_text", "") for attempt in attempts if attempt.get("question_text")])
    recent_questions = [item for item in recent_questions if item][-40:]

    jd_overview = document.get("jd_overview") if isinstance(document.get("jd_overview"), dict) else {}
    role_title = str(session.get("role_title") or jd_overview.get("role_title") or "")
    required_skills = [
        str(item).strip()
        for item in (session.get("required_skills") or jd_overview.get("required_skills") or [])
        if str(item).strip()
    ]
    key_requirements = [
        str(item).strip()
        for item in (session.get("key_requirements") or jd_overview.get("key_requirements") or [])
        if str(item).strip()
    ]
    key_requirements = [item for item in key_requirements if not _is_non_skill_requirement(item)]
    resume_skills = [str(item).strip() for item in (session.get("resume_skills") or []) if str(item).strip()]
    input_type = str(session.get("input_type") or "jd").strip().lower() or "jd"
    resume_text = str(session.get("resume_text") or "")
    variation_seed = str(session.get("_id") or "")
    if input_type == "resume":
        focus_skills = list(dict.fromkeys([*resume_skills, *required_skills]))[:12]
    else:
        focus_skills = list(dict.fromkeys(required_skills))[:12]
    if not focus_skills:
        fallback_skill_blob = " ".join(
            [
                str(document.get("raw_text") or "")[:12000],
                " ".join(key_requirements),
                resume_text[:6000],
                role_title,
            ]
        )
        focus_skills = question_engine.extract_skill_hints_from_text(fallback_skill_blob, max_items=12)
        if focus_skills and not required_skills:
            required_skills = focus_skills[:]
    if not focus_skills:
        focus_skills = question_engine.infer_role_skill_defaults(role_title)
        if focus_skills and not required_skills:
            required_skills = focus_skills[:]

    max_generation_attempts = 6
    tried_chunk_ids: list[uuid.UUID] = []
    target_chunk = None
    question_text = ""
    expected_answer = ""

    document_uuid = await as_uuid(session.get("document_id"))
    if not document_uuid:
        raise HTTPException(status_code=500, detail="Invalid session document reference")

    for _ in range(max_generation_attempts):
        try:
            candidate_chunk = await pick_chunk_for_session_async(
                db,
                document_uuid,
                int(session.get("total_answered", 0)),
                int(session.get("current_difficulty", 1)),
                usage_counts=usage_counts,
                recent_chunk_ids=recent_chunk_ids,
                exclude_chunk_ids=tried_chunk_ids,
                role_title=role_title,
                focus_skills=focus_skills,
            )
        except ValueError:
            break

        try:
            candidate_question, candidate_answer = await question_engine.generate_question(
                context=candidate_chunk.text,
                difficulty=int(session.get("current_difficulty", 1)),
                recent_questions=recent_questions,
                attempt_index=int(session.get("total_answered", 0)),
                require_llm=False,
                role_title=role_title,
                required_skills=required_skills,
                key_requirements=key_requirements,
                resume_skills=resume_skills,
                input_type=input_type,
                strict_skill_mode=True,
                resume_text=resume_text,
                variation_seed=variation_seed,
            )
        except RuntimeError as exc:
            detail = str(exc)
            lowered = detail.lower()
            if "skill-focused question" in lowered or "derive any skill-focused" in lowered:
                tried_chunk_ids.append(candidate_chunk.id)
                usage_counts[candidate_chunk.id] += 1
                continue
            if "not configured" in lowered or "quota" in lowered:
                status_code = 503
            elif "invalid question format" in lowered:
                status_code = 422
            else:
                status_code = 502
            raise HTTPException(status_code=status_code, detail=detail) from exc

        if await question_engine.is_production_ready(
            question=candidate_question,
            answer=candidate_answer,
            recent_questions=recent_questions,
        ) and question_engine.text_mentions_focus_skill(candidate_question, focus_skills) and not question_engine.contains_non_skill_noise(candidate_question):
            target_chunk = candidate_chunk
            question_text = candidate_question
            expected_answer = candidate_answer
            break

        tried_chunk_ids.append(candidate_chunk.id)
        usage_counts[candidate_chunk.id] += 1

    if not target_chunk:
        try:
            fallback_chunk = await pick_chunk_for_session_async(
                db,
                document_uuid,
                int(session.get("total_answered", 0)),
                int(session.get("current_difficulty", 1)),
                usage_counts=usage_counts,
                recent_chunk_ids=[],
                role_title=role_title,
                focus_skills=focus_skills,
            )
        except ValueError:
            fallback_chunk = None

        if fallback_chunk is not None:
            try:
                fallback_question, fallback_answer = await question_engine.generate_question(
                    context=fallback_chunk.text,
                    difficulty=int(session.get("current_difficulty", 1)),
                    recent_questions=[],
                    attempt_index=int(session.get("total_answered", 0)),
                    require_llm=False,
                    role_title=role_title,
                    required_skills=required_skills,
                    key_requirements=key_requirements,
                    resume_skills=resume_skills,
                    input_type=input_type,
                    strict_skill_mode=True,
                    resume_text=resume_text,
                    variation_seed=variation_seed,
                )
            except RuntimeError:
                fallback_question, fallback_answer = "", ""
            if (
                fallback_question
                and fallback_answer
                and await question_engine.is_production_ready(
                    question=fallback_question,
                    answer=fallback_answer,
                    recent_questions=recent_questions,
                )
                and question_engine.text_mentions_focus_skill(fallback_question, focus_skills)
                and not question_engine.contains_non_skill_noise(fallback_question)
            ):
                question_text = fallback_question
                expected_answer = fallback_answer
                target_chunk = fallback_chunk

    if not target_chunk:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not build a skill-focused interview question from this document. "
                "Please upload a cleaner JD/resume with explicit skill keywords (for example: Python, SQL, React, API, Docker)."
            ),
        )

    attempt_id = str(uuid.uuid4())
    await attempts_collection.insert_one(
        {
            "_id": attempt_id,
            "session_id": session["_id"],
            "owner_id": owner_id,
            "owner_email": owner_email or session.get("owner_email"),
            "question_text": question_text,
            "expected_answer": expected_answer,
            "difficulty": int(session.get("current_difficulty", 1)),
            "source_chunk_id": str(target_chunk.id),
            "user_answer": None,
            "is_correct": None,
            "created_at": await utcnow(),
        }
    )

    return attempt_id, question_text, int(session.get("current_difficulty", 1))
