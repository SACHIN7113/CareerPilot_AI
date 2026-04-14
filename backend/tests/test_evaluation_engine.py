import asyncio

from app.services.evaluation_engine import EvaluationEngine


def _run(coro):
    return asyncio.run(coro)


def test_skip_intent_is_marked_incorrect() -> None:
    engine = EvaluationEngine()
    is_correct, feedback = _run(
        engine.evaluate(expected_answer="Python is a programming language.", user_answer="I don't know")
    )

    assert is_correct is False
    assert "share the answer" in feedback.lower()


def test_fallback_requires_keyword_match() -> None:
    engine = EvaluationEngine()
    is_correct, _feedback = engine._fallback_evaluate(
        expected_answer="Python is a high-level programming language used for automation.",
        user_answer="Python is a programming language used for automation tasks.",
    )

    assert is_correct is True


def test_fallback_rejects_unrelated_long_answer() -> None:
    engine = EvaluationEngine()
    is_correct, feedback = engine._fallback_evaluate(
        expected_answer="The CPU executes instructions and performs calculations.",
        user_answer="This answer is long but it talks about gardening, soil, sunlight, and watering plants every day.",
    )

    assert is_correct is False
    assert "document" in feedback.lower()


def test_fallback_accepts_semantic_paraphrase_with_different_wording() -> None:
    engine = EvaluationEngine()
    is_correct, feedback = engine._fallback_evaluate(
        expected_answer=(
            "Python is a high-level, interpreted, object-oriented programming language "
            "known for its simplicity and readability."
        ),
        user_answer=(
            "Python is a high level interpreter language. It is simple to use, readable, "
            "and used for machine learning and web development."
        ),
    )

    assert is_correct is True
    assert "correct" in feedback.lower()


def test_fallback_accepts_core_meaning_when_minor_detail_is_missing() -> None:
    engine = EvaluationEngine()
    is_correct, feedback = engine._fallback_evaluate(
        expected_answer="NumPy is used for numerical computing and array operations.",
        user_answer="NumPy is a library used for numerical computing.",
    )

    assert is_correct is True
    assert "correct" in feedback.lower()
