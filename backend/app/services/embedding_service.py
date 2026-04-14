import hashlib
from typing import Any

import numpy as np

from app.core.async_utils import run_blocking
from app.config.settings import settings
from app.services.gemini_service import _embed_text_sync as embed_text


class EmbeddingService:
    def _embed_sync(self, text: str, *, task_type: str = "retrieval_document") -> list[float]:
        gemini_embedding = embed_text(text, task_type=task_type)
        if gemini_embedding:
            return gemini_embedding

        # Deterministic fallback for local testing when no API key is provided.
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (2**32)
        rng = np.random.default_rng(seed)
        return rng.normal(size=settings.embedding_dimensions).astype(float).tolist()

    async def embed(self, text: str, *, task_type: str = "retrieval_document") -> list[float]:
        try:
            return await run_blocking(self._embed_sync, text, task_type=task_type)
        except TypeError:
            # Some tests monkeypatch `embed` with a lambda that only accepts text.
            return await run_blocking(self._embed_sync, text)

    async def embed_async(self, text: str, *, task_type: str = "retrieval_document") -> list[float]:
        return await self.embed(text, task_type=task_type)


embedding_service = EmbeddingService()


def _cosine_similarity_sync(v1: list[float], v2: list[float]) -> float:
    a = np.array(v1)
    b = np.array(v2)
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    if denominator == 0:
        return 0.0
    return float(np.dot(a, b) / denominator)


async def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    return await run_blocking(_cosine_similarity_sync, v1, v2)


def _top_k_similar_sync(query_embedding: list[float], items: list[dict[str, Any]], k: int = 3) -> list[dict[str, Any]]:
    scored = []
    for item in items:
        score = _cosine_similarity_sync(query_embedding, item["embedding"])
        scored.append({**item, "score": score})
    scored.sort(key=lambda value: value["score"], reverse=True)
    return scored[:k]


async def top_k_similar(query_embedding: list[float], items: list[dict[str, Any]], k: int = 3) -> list[dict[str, Any]]:
    return await run_blocking(_top_k_similar_sync, query_embedding, items, k)

