import json
from collections.abc import Iterable

import google.generativeai as genai

from app.core.async_utils import run_blocking
from app.config.settings import settings

_configured = False
_DEFAULT_GENERATION_MODELS = (
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.5-flash-lite",
    "models/gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
)


def _ensure_configured() -> bool:
    global _configured
    if not settings.gemini_api_key:
        return False
    if not _configured:
        genai.configure(api_key=settings.gemini_api_key)
        _configured = True
    return True


def _get_model_sync(model_name: str | None = None):
    if not _ensure_configured():
        return None
    return genai.GenerativeModel(model_name or settings.gemini_model)


async def get_model(model_name: str | None = None):
    return await run_blocking(_get_model_sync, model_name)


def _to_model_list(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]

    models: list[str] = []
    for item in value:
        model_name = str(item or "").strip()
        if model_name:
            models.append(model_name)
    return models


def _generation_model_names_sync(preferred_models: Iterable[str] | None = None) -> list[str]:
    ordered_candidates = [
        *_to_model_list(preferred_models),
        settings.gemini_model,
        *_to_model_list(settings.gemini_model_fallbacks),
        *_DEFAULT_GENERATION_MODELS,
    ]

    seen: set[str] = set()
    ordered: list[str] = []
    for item in ordered_candidates:
        model_name = str(item or "").strip()
        if not model_name or model_name in seen:
            continue
        ordered.append(model_name)
        seen.add(model_name)
    return ordered


def _generate_content_with_fallback_sync(
    *,
    prompt: str,
    generation_config: dict | None = None,
    preferred_models: Iterable[str] | None = None,
):
    if not _ensure_configured():
        raise RuntimeError("LLM model is not configured. Set GEMINI_API_KEY first.")

    last_error: Exception | None = None
    for model_name in _generation_model_names_sync(preferred_models):
        model = _get_model_sync(model_name)
        if model is None:
            continue
        try:
            response = model.generate_content(prompt, generation_config=generation_config)
            return response, model_name
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        message = str(last_error)
        if "resource_exhausted" in message.lower() or "quota" in message.lower() or "429" in message:
            raise RuntimeError("LLM quota exceeded for configured model(s).") from last_error
        raise RuntimeError(f"LLM request failed across all configured models: {message[:220]}") from last_error

    raise RuntimeError("No Gemini model could be initialized for content generation.")


async def generate_content_with_fallback(
    *,
    prompt: str,
    generation_config: dict | None = None,
    preferred_models: Iterable[str] | None = None,
):
    return await run_blocking(
        _generate_content_with_fallback_sync,
        prompt=prompt,
        generation_config=generation_config,
        preferred_models=preferred_models,
    )


def _extract_text_sync(response) -> str:
    text = getattr(response, "text", "") or ""
    if text:
        return text.strip()

    candidates = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", []) if content else []
        for part in parts:
            part_text = getattr(part, "text", "")
            if part_text:
                candidates.append(part_text)
    return "\n".join(candidates).strip()


async def extract_text(response) -> str:
    return await run_blocking(_extract_text_sync, response)


def _parse_json_response_sync(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text or "{}")


async def parse_json_response(raw_text: str) -> dict:
    return await run_blocking(_parse_json_response_sync, raw_text)


def _embed_text_sync(text: str, *, task_type: str) -> list[float] | None:
    if not _ensure_configured():
        return None

    candidate_models = [
        settings.gemini_embedding_model,
        "models/embedding-001",
    ]

    for model_name in dict.fromkeys(candidate_models):
        kwargs = {
            "model": model_name,
            "content": text,
            "task_type": task_type,
        }
        try:
            try:
                response = genai.embed_content(**kwargs, output_dimensionality=settings.embedding_dimensions)
            except TypeError:
                response = genai.embed_content(**kwargs)

            if isinstance(response, dict):
                vector = response.get("embedding", [])
            else:
                vector = getattr(response, "embedding", [])

            vector = [float(value) for value in vector]
            if len(vector) == settings.embedding_dimensions:
                return vector
            if len(vector) > settings.embedding_dimensions:
                return vector[: settings.embedding_dimensions]
            return vector + [0.0] * (settings.embedding_dimensions - len(vector))
        except Exception:
            continue

    # If Gemini embedding fails for all candidates, caller can use local fallback.
    return None


async def embed_text(text: str, *, task_type: str) -> list[float] | None:
    return await run_blocking(_embed_text_sync, text, task_type=task_type)
