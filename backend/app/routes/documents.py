from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.db import COLLECTIONS, get_db
from app.core.dependencies import get_current_user
from app.models.api_schemas import DocumentOut
from app.services.document_parser import UnsupportedFileTypeError, extract_text_async
from app.services.document_workflow_service import (
    enrich_documents_with_overview,
    to_document_out,
    upsert_document_with_chunks,
)

router = APIRouter()


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    with_overview: bool = Query(default=True),
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> list[DocumentOut]:
    documents = db[COLLECTIONS["documents"]]
    rows = await documents.find({"owner_id": current_user["_id"]}).sort("created_at", -1).to_list(length=None)

    if with_overview:
        await enrich_documents_with_overview(documents=documents, rows=rows)
    return [await to_document_out(row) for row in rows]

@router.get("/count")
async def count_documents(
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, int]:
    documents = db[COLLECTIONS["documents"]]
    total = await documents.count_documents({"owner_id": current_user["_id"]})
    return {"count": int(total)}


@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> DocumentOut:
    documents = db[COLLECTIONS["documents"]]
    chunks_collection = db[COLLECTIONS["document_chunks"]]

    file_bytes = await file.read()
    try:
        raw_text = await extract_text_async(file.filename or "uploaded_file", file_bytes)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from document")
    try:
        return await upsert_document_with_chunks(
            documents=documents,
            chunks_collection=chunks_collection,
            owner_id=current_user["_id"],
            owner_email=str(current_user.get("email") or "").strip().lower() or None,
            filename=file.filename or "untitled",
            raw_text=raw_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


