from io import BytesIO
import re

import docx
from pypdf import PdfReader

from app.core.async_utils import run_blocking


class UnsupportedFileTypeError(Exception):
    pass


def _extract_text_sync(filename: str, data: bytes) -> str:
    lower_name = filename.lower()
    if lower_name.endswith(".txt"):
        return data.decode("utf-8", errors="ignore").strip()
    if lower_name.endswith(".pdf"):
        reader = PdfReader(BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return text.strip()
    if lower_name.endswith(".docx"):
        document = docx.Document(BytesIO(data))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        return text.strip()
    raise UnsupportedFileTypeError("Only .txt, .pdf, and .docx files are supported")


async def extract_text(filename: str, data: bytes) -> str:
    return await run_blocking(_extract_text_sync, filename, data)


async def extract_text_async(filename: str, data: bytes) -> str:
    return await extract_text(filename, data)


def _chunk_text_sync(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    if not text:
        return []

    normalized = re.sub(r"\r\n?", "\n", text).strip()
    if not normalized:
        return []

    segments = _build_segments(normalized, chunk_size)
    if not segments:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for segment in segments:
        segment_length = len(segment)
        projected = current_length + segment_length + (1 if current else 0)
        if current and projected > chunk_size:
            chunks.append("\n".join(current).strip())
            current = _carry_overlap(current, overlap)
            current_length = _joined_length(current)

        current.append(segment)
        current_length = _joined_length(current)

    if current:
        chunks.append("\n".join(current).strip())

    return [chunk for chunk in chunks if chunk]


async def chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    return await run_blocking(_chunk_text_sync, text, chunk_size, overlap)


async def chunk_text_async(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    return await chunk_text(text, chunk_size, overlap)


def _build_segments(text: str, chunk_size: int) -> list[str]:
    segments: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue

        lines = [line.strip() for line in block.splitlines() if line.strip()]
        source_segments = lines if len(lines) > 1 else [block]
        for segment in source_segments:
            segments.extend(_split_long_segment(segment, chunk_size))

    return segments


def _split_long_segment(segment: str, chunk_size: int) -> list[str]:
    segment = segment.strip()
    if not segment:
        return []
    if len(segment) <= chunk_size:
        return [segment]

    parts: list[str] = []
    words = segment.split()
    current: list[str] = []
    current_length = 0
    for word in words:
        projected = current_length + len(word) + (1 if current else 0)
        if current and projected > chunk_size:
            parts.append(" ".join(current).strip())
            current = [word]
            current_length = len(word)
            continue
        current.append(word)
        current_length = projected

    if current:
        parts.append(" ".join(current).strip())
    return [part for part in parts if part]


def _carry_overlap(segments: list[str], overlap: int) -> list[str]:
    carried: list[str] = []
    total = 0
    for segment in reversed(segments):
        segment_length = len(segment)
        if not carried and segment_length > overlap:
            break
        extra_separator = 1 if carried else 0
        if carried and total + segment_length + extra_separator > overlap:
            break
        carried.insert(0, segment)
        total += segment_length + extra_separator
        if total >= overlap:
            break
    return carried


def _joined_length(segments: list[str]) -> int:
    if not segments:
        return 0
    return sum(len(segment) for segment in segments) + max(0, len(segments) - 1)
