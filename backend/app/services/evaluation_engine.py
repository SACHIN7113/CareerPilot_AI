import re
from difflib import SequenceMatcher

from app.core.async_utils import run_blocking
from app.services.gemini_service import (
    _extract_text_sync as extract_text,
    _generate_content_with_fallback_sync as generate_content_with_fallback,
    _get_model_sync as get_model,
    _parse_json_response_sync as parse_json_response,
)


class EvaluationEngine:
    _SKIP_PATTERNS = (
        "i dont know",
        "i don't know",
        "i don t know",
        "dont know",
        "don't know",
        "don t know",
        "skip",
        "next question",
        "move further",
        "go further",
        "show answer",
        "tell me the answer",
        "tell me correct answer",
        "tell me the correct answer",
    )
    _STOP_WORDS = {
        "about",
        "after",
        "again",
        "also",
        "been",
        "being",
        "between",
        "both",
        "could",
        "does",
        "from",
        "have",
        "into",
        "just",
        "more",
        "most",
        "only",
        "other",
        "over",
        "same",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "very",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "would",
        "your",
    }

    def __init__(self) -> None:
        self.model = get_model()

    def _evaluate_sync(self, *, expected_answer: str, user_answer: str) -> tuple[bool, str]:
        if self._is_skip_intent(user_answer):
            return False, "No problem. I will share the answer and move to the next question."

        if self.model:
            try:
                return self._llm_evaluate(expected_answer=expected_answer, user_answer=user_answer)
            except Exception:
                # Keep the answer flow available when provider quota or rate limits are hit.
                return self._fallback_evaluate(expected_answer=expected_answer, user_answer=user_answer)
        return self._fallback_evaluate(expected_answer=expected_answer, user_answer=user_answer)

    async def evaluate(self, *, expected_answer: str, user_answer: str) -> tuple[bool, str]:
        return await run_blocking(self._evaluate_sync, expected_answer=expected_answer, user_answer=user_answer)

    async def evaluate_async(self, *, expected_answer: str, user_answer: str) -> tuple[bool, str]:
        return await self.evaluate(expected_answer=expected_answer, user_answer=user_answer)

    def _llm_evaluate(self, *, expected_answer: str, user_answer: str) -> tuple[bool, str]:
        prompt = (
            "You are evaluating a learner's answer against a reference answer from a document.\n"
            "Judge meaning, not exact wording.\n"
            "Treat paraphrases, synonyms, reordered ideas, spelling mistakes, and imperfect grammar as acceptable.\n"
            "Use CORRECT when the learner captures the main meaning, even if they miss a minor detail.\n"
            "Use PARTIAL when the learner mentions a related idea but misses the core explanation.\n"
            "Use INCORRECT when the answer is wrong, unrelated, or the learner asks to skip.\n"
            "Return only JSON in this format: "
            '{"verdict":"CORRECT|PARTIAL|INCORRECT","feedback":"one short supportive sentence"}'
        )
        response, _used_model = generate_content_with_fallback(
            prompt=f"{prompt}\n\nExpected: {expected_answer}\nStudent: {user_answer}",
            generation_config={"temperature": 0.1, "response_mime_type": "application/json"},
        )
        raw = extract_text(response) or "{}"
        try:
            parsed = parse_json_response(raw)
        except Exception:
            return self._fallback_evaluate(expected_answer=expected_answer, user_answer=user_answer)

        verdict = str(parsed.get("verdict", "")).strip().upper()
        feedback = str(parsed.get("feedback", "")).strip()

        if verdict not in {"CORRECT", "PARTIAL", "INCORRECT"}:
            return self._fallback_evaluate(expected_answer=expected_answer, user_answer=user_answer)

        if verdict == "CORRECT":
            return True, feedback or "Correct. You captured the main idea from the document."
        if verdict == "PARTIAL":
            return False, feedback or "Partly right, but one important idea is still missing."
        return False, feedback or "That does not match the document closely enough yet."

    def _fallback_evaluate(self, *, expected_answer: str, user_answer: str) -> tuple[bool, str]:
        normalized_expected = self._normalize_text(expected_answer)
        normalized_user = self._normalize_text(user_answer)
        if not normalized_user:
            return False, "I could not validate that response. Try answering in a short sentence."

        if normalized_expected and normalized_user == normalized_expected:
            return True, "Correct. Your answer matches the document closely."

        expected_keywords = self._keywords(expected_answer)
        user_keywords = self._keywords(user_answer)

        if normalized_expected and normalized_user in normalized_expected and len(normalized_user.split()) >= 3:
            return True, "Correct. Your answer is directly supported by the document."

        if expected_keywords:
            overlap = self._keyword_overlap(expected_keywords, user_keywords)
            coverage = len(overlap) / len(expected_keywords)
            if coverage >= 0.45:
                return True, "Correct. You covered the main idea from the document."
            if len(expected_keywords) <= 4 and len(overlap) >= max(2, len(expected_keywords) - 1):
                return True, "Correct. You captured the key terms from the document."
            if self._shares_subject(expected_answer, user_answer) and len(overlap) >= 2:
                return True, "Correct overall. Your wording is different, but the main idea is right."
            if coverage >= 0.25:
                return False, "Partly right, but an important detail is still missing."
            return False, "That does not match the document closely enough yet."

        if len(normalized_user.split()) >= 8:
            return True, "Good answer. You gave a complete explanation."
        return False, "Please add a little more detail from the document."

    def _is_skip_intent(self, user_answer: str) -> bool:
        normalized = self._normalize_text(user_answer)
        return any(pattern in normalized for pattern in self._SKIP_PATTERNS)

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", value.lower())).strip()

    def _keywords(self, value: str) -> list[str]:
        keywords: list[str] = []
        seen: set[str] = set()
        for token in re.findall(r"[a-zA-Z][a-zA-Z'-]*", value.lower()):
            normalized = self._normalize_token(token)
            if len(normalized) < 4 or normalized in self._STOP_WORDS:
                continue
            if normalized in seen:
                continue
            keywords.append(normalized)
            seen.add(normalized)
        return keywords

    def _normalize_token(self, token: str) -> str:
        normalized = token.strip("' -")
        for suffix in ("ing", "ed", "es", "s"):
            if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 4:
                return normalized[: -len(suffix)]
        return normalized

    def _keyword_overlap(self, expected_keywords: list[str], user_keywords: list[str]) -> set[str]:
        overlap: set[str] = set()
        for expected in expected_keywords:
            for candidate in user_keywords:
                if self._tokens_match(expected, candidate):
                    overlap.add(expected)
                    break
        return overlap

    def _tokens_match(self, expected: str, candidate: str) -> bool:
        if expected == candidate:
            return True
        if len(expected) >= 5 and len(candidate) >= 5 and (expected in candidate or candidate in expected):
            return True

        prefix_size = min(len(expected), len(candidate), 7)
        if prefix_size >= 5 and expected[:prefix_size] == candidate[:prefix_size]:
            return True

        return SequenceMatcher(a=expected, b=candidate).ratio() >= 0.84

    def _shares_subject(self, expected_answer: str, user_answer: str) -> bool:
        expected_subject = self._subject_tokens(expected_answer)
        user_subject = self._subject_tokens(user_answer)
        return bool(expected_subject and user_subject and self._keyword_overlap(expected_subject, user_subject))

    def _subject_tokens(self, value: str) -> list[str]:
        subject_match = re.match(
            r"^\s*(?P<subject>[A-Za-z][A-Za-z0-9+/#' -]{1,80}?)\s+(?:is|are|means|refers to|describes|includes)\b",
            value.strip(),
            flags=re.IGNORECASE,
        )
        if subject_match:
            return self._keywords(subject_match.group("subject"))
        return self._keywords(" ".join(value.split()[:5]))


evaluation_engine = EvaluationEngine()
