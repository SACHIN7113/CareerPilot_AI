from app.services.skill_roadmap_service import (
    _candidate_model_names,
    _fallback_detailed_plan,
    _fallback_roadmap,
)


def test_candidate_model_order_prefers_gemini_25_flash_first() -> None:
    names = _candidate_model_names()

    assert names
    assert names[0] == "models/gemini-2.5-flash"
    assert len(names) == len(set(names))


def test_windows_os_fallback_plan_avoids_generic_interview_boilerplate() -> None:
    roadmap = _fallback_roadmap("Windows OS")

    text_blob = " ".join(
        [
            roadmap.get("overview", ""),
            " ".join(roadmap.get("projects", [])),
            " ".join(roadmap.get("resources", [])),
            " ".join(
                item
                for step in roadmap.get("roadmap_steps", [])
                for item in step.get("action_items", [])
            ),
        ]
    ).lower()

    assert "task manager" in text_blob
    assert "command prompt" in text_blob or "ipconfig" in text_blob or "ping" in text_blob
    assert "resume bullets" not in text_blob
    assert "mock interview" not in text_blob


def test_communication_fallback_plan_includes_tense_and_speaking() -> None:
    plan = _fallback_detailed_plan("Communication Skills")
    text_blob = " ".join(
        [
            " ".join(str(item.get("subtopics", [])) for item in plan),
            " ".join(str(item.get("practice", [])) for item in plan),
        ]
    ).lower()

    assert "tense" in text_blob
    assert "speaking" in text_blob
    assert "pronunciation" in text_blob or "listening" in text_blob
