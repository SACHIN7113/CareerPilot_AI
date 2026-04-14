import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from app.models.api_schemas import DocumentOut
from app.services.document_parser import chunk_text
from app.services.embedding_service import embedding_service
from app.services.jd_overview_service import build_jd_overview


def _needs_identity_refresh(company_name: str, role_title: str) -> bool:
    company = str(company_name or "").strip().lower()
    role = str(role_title or "").strip().lower()

    if company in {"", "the company"} or role in {"", "this role"}:
        return True

    noisy_company = any(token in company for token in ("join our team", "if you think", "ctc", "lpa", "job description"))
    noisy_role = any(token in role for token in ("if you think", "ctc", "lpa", "job description", "salary"))
    too_long_company = len(company.split()) > 6
    too_long_role = len(role.split()) > 8

    return noisy_company or noisy_role or too_long_company or too_long_role


async def enrich_documents_with_overview(*, documents: AsyncIOMotorCollection, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        existing_overview = row.get("jd_overview") if isinstance(row.get("jd_overview"), dict) else {}
        if existing_overview and existing_overview.get("generated_by") in {"llm", "fallback"}:
            if not _needs_identity_refresh(
                existing_overview.get("company_name") or "",
                existing_overview.get("role_title") or "",
            ):
                continue
        raw_text = str(row.get("raw_text") or "")
        if not raw_text.strip():
            continue
        jd_overview = await build_jd_overview(raw_text, filename=str(row.get("title") or ""))
        await documents.update_one({"_id": row["_id"]}, {"$set": {"jd_overview": jd_overview}})
        row["jd_overview"] = jd_overview


async def to_document_out(row: dict[str, Any]) -> DocumentOut:
    return DocumentOut(
        id=row["_id"],
        title=row["title"],
        content_hash=row["content_hash"],
        created_at=row["created_at"],
        jd_overview=row.get("jd_overview"),
    )


async def upsert_document_with_chunks(
    *,
    documents: AsyncIOMotorCollection,
    chunks_collection: AsyncIOMotorCollection,
    owner_id: str,
    owner_email: str | None = None,
    filename: str,
    raw_text: str,
) -> DocumentOut:
    jd_overview = await build_jd_overview(raw_text, filename=filename)
    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    existing = await documents.find_one({"owner_id": owner_id, "content_hash": content_hash})

    if existing:
        await chunks_collection.delete_many({"document_id": existing["_id"]})
        await documents.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "title": filename or existing["title"],
                    "raw_text": raw_text,
                    "jd_overview": jd_overview,
                    "owner_email": owner_email or existing.get("owner_email"),
                }
            },
        )

        chunks = await chunk_text(raw_text)
        for index, chunk in enumerate(chunks):
            embedding = await embedding_service.embed_async(chunk, task_type="retrieval_document")
            await chunks_collection.insert_one(
                {
                    "_id": str(uuid.uuid4()),
                    "document_id": existing["_id"],
                    "owner_id": owner_id,
                    "owner_email": owner_email,
                    "chunk_index": index,
                    "text": chunk,
                    "embedding": embedding,
                }
            )

        updated = await documents.find_one({"_id": existing["_id"]})
        return await to_document_out(updated)

    chunks = await chunk_text(raw_text)
    if not chunks:
        raise ValueError("Document has no meaningful text")

    document_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    await documents.insert_one(
        {
            "_id": document_id,
            "owner_id": owner_id,
            "owner_email": owner_email,
            "title": filename or "untitled",
            "content_hash": content_hash,
            "raw_text": raw_text,
            "jd_overview": jd_overview,
            "created_at": created_at,
        }
    )

    for index, chunk in enumerate(chunks):
        embedding = await embedding_service.embed_async(chunk, task_type="retrieval_document")
        await chunks_collection.insert_one(
            {
                "_id": str(uuid.uuid4()),
                "document_id": document_id,
                "owner_id": owner_id,
                "owner_email": owner_email,
                "chunk_index": index,
                "text": chunk,
                "embedding": embedding,
            }
        )

    created = await documents.find_one({"_id": document_id})
    return await to_document_out(created)
