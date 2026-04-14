import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.database import Database

from app.core.async_utils import run_blocking
from app.config.db import COLLECTIONS
from app.services.difficulty_controller import difficulty_label
from app.services.embedding_service import _cosine_similarity_sync as cosine_similarity, embedding_service


@dataclass
class ChunkRecord:
    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    text: str
    embedding: list[float]


def _difficulty_label_sync(level: int) -> str:
    mapping = {1: "easy", 2: "medium", 3: "hard"}
    return mapping.get(level, "easy")


def _build_retrieval_query_sync(
    answered_count: int,
    difficulty: int,
    *,
    role_title: str = "",
    focus_skills: Sequence[str] | None = None,
) -> str:
    role = re.sub(r"\s+", " ", str(role_title or "").strip())
    skills = [re.sub(r"\s+", " ", str(item or "").strip()) for item in (focus_skills or []) if str(item or "").strip()]
    skills = list(dict.fromkeys(skills))[:8]

    skill_hint = f" Focus skills: {', '.join(skills)}." if skills else ""
    role_hint = f" Role context: {role}." if role else ""
    return (
        f"Generate a {_difficulty_label_sync(difficulty)} question for learner turn {answered_count + 1}. "
        "Prefer chunks rich in explicit facts, definitions, examples, and teachable concepts."
        f"{role_hint}{skill_hint}"
    )


async def build_retrieval_query(
    answered_count: int,
    difficulty: int,
    *,
    role_title: str = "",
    focus_skills: Sequence[str] | None = None,
) -> str:
    label = await difficulty_label(difficulty)
    role = re.sub(r"\s+", " ", str(role_title or "").strip())
    skills = [re.sub(r"\s+", " ", str(item or "").strip()) for item in (focus_skills or []) if str(item or "").strip()]
    skills = list(dict.fromkeys(skills))[:8]
    skill_hint = f" Focus skills: {', '.join(skills)}." if skills else ""
    role_hint = f" Role context: {role}." if role else ""
    return (
        f"Generate a {label} question for learner turn {answered_count + 1}. "
        "Prefer chunks rich in explicit facts, definitions, examples, and teachable concepts."
        f"{role_hint}{skill_hint}"
    )


def _retrieve_relevant_chunks_sync(
    db: Database,
    document_id: uuid.UUID,
    query_embedding: list[float],
    limit: int = 8,
) -> list[ChunkRecord]:
    rows = list(db[COLLECTIONS["document_chunks"]].find({"document_id": str(document_id)}))
    scored: list[tuple[float, dict]] = []
    for row in rows:
        embedding = row.get("embedding") or []
        score = cosine_similarity(query_embedding, embedding) if embedding else -1.0
        scored.append((score, row))

    scored.sort(key=lambda item: (-item[0], item[1].get("chunk_index", 0)))

    chunks: list[ChunkRecord] = []
    for _score, row in scored[:limit]:
        try:
            chunk_id = uuid.UUID(str(row.get("_id")))
        except (TypeError, ValueError):
            continue
        try:
            doc_id = uuid.UUID(str(row.get("document_id")))
        except (TypeError, ValueError):
            continue

        chunks.append(
            ChunkRecord(
                id=chunk_id,
                document_id=doc_id,
                chunk_index=int(row.get("chunk_index", 0)),
                text=str(row.get("text", "")),
                embedding=list(row.get("embedding") or []),
            )
        )
    return chunks


async def retrieve_relevant_chunks(
    db: Database,
    document_id: uuid.UUID,
    query_embedding: list[float],
    limit: int = 8,
) -> list[ChunkRecord]:
    return await run_blocking(_retrieve_relevant_chunks_sync, db, document_id, query_embedding, limit)


async def retrieve_relevant_chunks_async(
    db: AsyncIOMotorDatabase,
    document_id: uuid.UUID,
    query_embedding: list[float],
    limit: int = 8,
) -> list[ChunkRecord]:
    rows = await db[COLLECTIONS["document_chunks"]].find({"document_id": str(document_id)}).to_list(length=None)
    scored: list[tuple[float, dict]] = []
    for row in rows:
        embedding = row.get("embedding") or []
        score = cosine_similarity(query_embedding, embedding) if embedding else -1.0
        scored.append((score, row))

    scored.sort(key=lambda item: (-item[0], item[1].get("chunk_index", 0)))

    chunks: list[ChunkRecord] = []
    for _score, row in scored[:limit]:
        try:
            chunk_id = uuid.UUID(str(row.get("_id")))
        except (TypeError, ValueError):
            continue
        try:
            doc_id = uuid.UUID(str(row.get("document_id")))
        except (TypeError, ValueError):
            continue

        chunks.append(
            ChunkRecord(
                id=chunk_id,
                document_id=doc_id,
                chunk_index=int(row.get("chunk_index", 0)),
                text=str(row.get("text", "")),
                embedding=list(row.get("embedding") or []),
            )
        )
    return chunks


async def choose_chunk_candidate(
    ranked_chunks: Sequence[ChunkRecord],
    *,
    usage_counts: Mapping[uuid.UUID, int] | None = None,
    recent_chunk_ids: Sequence[uuid.UUID] | None = None,
    answered_count: int = 0,
) -> ChunkRecord:
    _ = answered_count
    if not ranked_chunks:
        raise ValueError("Chunks cannot be empty")

    usage_counts = usage_counts or {}
    recent_chunk_ids = set(recent_chunk_ids or [])
    quality_scores = {chunk.id: await chunk_quality_score(chunk.text) for chunk in ranked_chunks}
    best_quality = max(quality_scores.values(), default=0)
    preferred_chunks = [chunk for chunk in ranked_chunks if quality_scores.get(chunk.id, 0) >= best_quality - 2]
    candidate_chunks = preferred_chunks or list(ranked_chunks)

    unused_chunks = [chunk for chunk in candidate_chunks if usage_counts.get(chunk.id, 0) == 0]
    if unused_chunks:
        pool = unused_chunks
    else:
        non_recent_chunks = [chunk for chunk in candidate_chunks if chunk.id not in recent_chunk_ids]
        pool = non_recent_chunks or candidate_chunks or list(ranked_chunks)

    pool = sorted(
        pool,
        key=lambda chunk: (usage_counts.get(chunk.id, 0), -quality_scores.get(chunk.id, 0), chunk.chunk_index),
    )
    return pool[0]


async def _embed_query(query_text: str) -> list[float]:
    try:
        return await embedding_service.embed(query_text, task_type="retrieval_query")
    except TypeError:
        # Older tests monkeypatch `embed` with a simple lambda that does not accept kwargs.
        return await embedding_service.embed(query_text)


async def pick_chunk_for_session(
    db: Database,
    document_id: uuid.UUID,
    answered_count: int,
    difficulty: int,
    *,
    usage_counts: Mapping[uuid.UUID, int] | None = None,
    recent_chunk_ids: Sequence[uuid.UUID] | None = None,
    exclude_chunk_ids: Sequence[uuid.UUID] | None = None,
    role_title: str = "",
    focus_skills: Sequence[str] | None = None,
) -> ChunkRecord:
    query_text = _build_retrieval_query_sync(
        answered_count,
        difficulty,
        role_title=role_title,
        focus_skills=focus_skills,
    )
    query_embedding = await _embed_query(query_text)
    ranked_chunks = await retrieve_relevant_chunks(db, document_id, query_embedding, limit=8)
    excluded = set(exclude_chunk_ids or [])
    if excluded:
        ranked_chunks = [chunk for chunk in ranked_chunks if chunk.id not in excluded]
    if not ranked_chunks:
        raise ValueError("No eligible document chunks found")
    return await choose_chunk_candidate(
        ranked_chunks,
        usage_counts=usage_counts,
        recent_chunk_ids=recent_chunk_ids,
        answered_count=answered_count,
    )


async def pick_chunk_for_session_async(
    db: AsyncIOMotorDatabase,
    document_id: uuid.UUID,
    answered_count: int,
    difficulty: int,
    *,
    usage_counts: Mapping[uuid.UUID, int] | None = None,
    recent_chunk_ids: Sequence[uuid.UUID] | None = None,
    exclude_chunk_ids: Sequence[uuid.UUID] | None = None,
    role_title: str = "",
    focus_skills: Sequence[str] | None = None,
) -> ChunkRecord:
    query_text = await build_retrieval_query(
        answered_count,
        difficulty,
        role_title=role_title,
        focus_skills=focus_skills,
    )
    query_embedding = await _embed_query(query_text)
    ranked_chunks = await retrieve_relevant_chunks_async(db, document_id, query_embedding, limit=8)
    excluded = set(exclude_chunk_ids or [])
    if excluded:
        ranked_chunks = [chunk for chunk in ranked_chunks if chunk.id not in excluded]
    if not ranked_chunks:
        raise ValueError("No eligible document chunks found")
    return await choose_chunk_candidate(
        ranked_chunks,
        usage_counts=usage_counts,
        recent_chunk_ids=recent_chunk_ids,
        answered_count=answered_count,
    )


def _chunk_quality_score_sync(text: str) -> int:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return -10

    score = 0
    question_mark_count = min(6, normalized.count("?"))
    answer_marker_count = len(re.findall(r"(?i)\b(?:answer|ans|a)\s*[:\-]", normalized))
    explicit_question_count = len(re.findall(r"(?im)^(?:\s*)(?:q(?:uestion)?\s*\d*|\d+)\s*[.):\-]", text or ""))
    wh_question_count = len(re.findall(r"(?i)\b(?:what|why|how|when|where|which|who)\b[^?]{0,120}\?", normalized))
    code_penalty = len(re.findall(r"[_(){}[\]<>=\"`]|\.py\b|\bimport\b|\bclass\b|\bdef\b|\breturn\b", normalized))

    score += question_mark_count * 2
    score += answer_marker_count * 3
    score += explicit_question_count * 4
    score += wh_question_count * 2
    score -= min(8, code_penalty)

    if re.search(r"(?i)\b(?:question|answer)\s*\d*\b", normalized):
        score += 2
    if len(normalized) < 80:
        score -= 2

    return score


async def chunk_quality_score(text: str) -> int:
    return await run_blocking(_chunk_quality_score_sync, text)

