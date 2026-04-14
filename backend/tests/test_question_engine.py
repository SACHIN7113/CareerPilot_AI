import asyncio

import pytest

from app.services.question_engine import QuestionEngine


def _run(coro):
    return asyncio.run(coro)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModel:
    def __init__(self, text: str) -> None:
        self._text = text

    def generate_content(self, _prompt: str, generation_config=None):
        _ = generation_config
        return _FakeResponse(self._text)


class _FailingModel:
    def generate_content(self, _prompt: str, generation_config=None):
        _ = generation_config
        raise RuntimeError("simulated llm failure")


def test_generate_question_prefers_inline_question_answer_pair() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context="1. What is Python? Answer: Python is a high-level interpreted object-oriented language.",
        difficulty=1,
    ))

    assert question == "What is Python?"
    assert answer.startswith("Python is")


def test_generate_question_does_not_leak_answer_label_into_question() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, _answer = _run(engine.generate_question(
        context="Answer: Python is a high-level interpreted object-oriented language used for automation.",
        difficulty=1,
    ))

    assert "answer" not in question.lower()
    assert question.endswith("?")


def test_generate_question_strips_plain_q_prefixes() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context=(
            "Q: What is NumPy? "
            "Answer: NumPy is used for numerical computing and array operations. "
            "Example: import numpy as np"
        ),
        difficulty=1,
    ))

    assert question == "What is NumPy?"
    assert answer == "NumPy is used for numerical computing and array operations."


def test_generate_question_converts_command_prompt_to_clean_question() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context="Question 4: Find majority element\nAnswer: Use a frequency count or Boyer-Moore voting algorithm.",
        difficulty=1,
    ))

    assert question == "How would you find majority element?"
    assert answer.startswith("Use a frequency count")


def test_generate_question_rejects_mixed_question_heads() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context=(
            'db.similarity_search("What is total amount?") '
            "How to Explain This Project in Interview. "
            "I built an AI-powered document assistant where users can upload PDFs and ask questions."
        ),
        difficulty=1,
    ))

    assert question == "What is AI-powered document assistant?"
    assert "upload pdfs" in answer.lower()


def test_generate_question_stops_answer_before_next_numbered_question() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context=(
            "Q10. What is exception handling? Used to handle runtime errors. "
            "Q11. What is OOP? Object-Oriented Programming organizes code using classes and objects."
        ),
        difficulty=1,
    ))

    assert question == "What is exception handling?"
    assert "runtime errors" in answer.lower()
    assert "what is oop" not in answer.lower()


def test_generate_question_removes_incomplete_provided_examples_phrase() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context=(
            "Q1: How do you swap two variables a and b in Python based on the provided examples? "
            "Answer: In Python, use tuple unpacking: a, b = b, a."
        ),
        difficulty=1,
    ))

    assert question == "How do you swap two variables a and b in Python?"
    assert "tuple unpacking" in answer.lower()


def test_generate_question_keeps_answer_content_when_for_example_is_present() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context=(
            "Q1. How do you swap two variables in Python? "
            "Answer: Use tuple unpacking: a, b = b, a. "
            "For example, if a=3 and b=4, after swap a=4 and b=3."
        ),
        difficulty=1,
    ))

    assert question == "How do you swap two variables in Python?"
    assert "tuple unpacking" in answer.lower()
    assert "for example" in answer.lower()


def test_generate_question_picks_next_numbered_entry_without_question_mark() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context=(
            "Q10. What is exception handling? Used to handle runtime errors. "
            "Q11. What is OOP Object-Oriented Programming organizes code using classes and objects."
        ),
        difficulty=1,
        recent_questions=["What is exception handling?"],
    ))

    assert question == "What is OOP?"
    assert "object-oriented programming" in answer.lower()


def test_is_production_ready_rejects_generic_main_idea_question() -> None:
    engine = QuestionEngine()

    assert not _run(engine.is_production_ready(
        question="What is the main idea of this passage?",
        answer="This paragraph talks about several coding interview exercises.",
    ))


def test_is_production_ready_accepts_clear_question_answer_pair() -> None:
    engine = QuestionEngine()

    assert _run(engine.is_production_ready(
        question="What is list comprehension?",
        answer="A concise way to build a list by iterating and applying an expression.",
    ))


def test_is_production_ready_rejects_question_repeated_later_in_session() -> None:
    engine = QuestionEngine()

    history = ["What is exception handling?"] + [f"Dummy question {i}?" for i in range(1, 12)]

    assert not _run(engine.is_production_ready(
        question="What is exception handling?",
        answer="It is used to handle runtime errors.",
        recent_questions=history,
    ))


def test_is_production_ready_rejects_paraphrased_repeated_question() -> None:
    engine = QuestionEngine()

    recent = ["What are the four core principles of Object-Oriented Programming mentioned in the text?"]
    candidate = "What are the four fundamental principles of Object-Oriented Programming as defined in the provided text?"

    assert not _run(engine.is_production_ready(
        question=candidate,
        answer="Inheritance, polymorphism, abstraction, and encapsulation.",
        recent_questions=recent,
    ))


def test_generate_question_require_llm_raises_when_model_missing() -> None:
    engine = QuestionEngine()
    engine.model = None
    engine._candidate_model_names = lambda: []

    with pytest.raises(RuntimeError, match="not configured"):
        _run(engine.generate_question(
            context="What is Python? Answer: Python is a language.",
            difficulty=1,
            require_llm=True,
        ))


def test_generate_question_require_llm_uses_model_output() -> None:
    engine = QuestionEngine()
    engine.model = _FakeModel("Question: What is Python?\nAnswer: Python is a programming language.")

    question, answer = _run(engine.generate_question(
        context="Python basics",
        difficulty=1,
        require_llm=True,
    ))

    assert question == "What is Python?"
    assert answer == "Python is a programming language."


def test_generate_question_non_required_llm_falls_back_on_model_failure() -> None:
    engine = QuestionEngine()
    engine.model = _FailingModel()
    engine._candidate_model_names = lambda: []

    question, answer = _run(engine.generate_question(
        context="Q1. What is Python? Answer: Python is an interpreted programming language.",
        difficulty=1,
        require_llm=False,
    ))

    assert question == "What is Python?"
    assert "interpreted programming language" in answer.lower()


def test_generate_question_uses_skill_metadata_for_role_specific_question() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context=(
            "Technical support associates handle customer tickets, diagnose issues, "
            "and communicate resolution updates clearly."
        ),
        difficulty=2,
        role_title="Technical Support Associate",
        required_skills=["Ticketing System", "Communication", "Troubleshooting"],
        key_requirements=["Handle customer queries and support tickets"],
        variation_seed="session-a",
    ))

    assert question.endswith("?")
    assert "ticket" in question.lower() or "communication" in question.lower() or "troubleshooting" in question.lower()
    assert "customer" in answer.lower() or "ticket" in answer.lower()


def test_generate_question_varies_with_different_variation_seed() -> None:
    engine = QuestionEngine()
    engine.model = None

    kwargs = {
        "context": (
            "This role requires Python, SQL, and API debugging for backend support tasks."
        ),
        "difficulty": 2,
        "role_title": "Backend Support Engineer",
        "required_skills": ["Python", "SQL", "API"],
        "key_requirements": ["Resolve backend integration issues"],
    }

    question_a, _ = _run(engine.generate_question(**kwargs, variation_seed="session-a"))
    question_b, _ = _run(engine.generate_question(**kwargs, variation_seed="session-b"))

    assert question_a.endswith("?")
    assert question_b.endswith("?")
    assert question_a != question_b


def test_generate_question_non_technical_role_uses_role_and_requirement_context() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context=(
            "Role: Customer Success Associate. "
            "The position requires communication, documentation, and stakeholder coordination "
            "to resolve onboarding blockers and improve retention."
        ),
        difficulty=2,
        role_title="Customer Success Associate",
        required_skills=["Communication", "Documentation", "Stakeholder Coordination"],
        key_requirements=["Resolve onboarding blockers", "Improve customer retention"],
        variation_seed="session-cs",
    ))

    lower_question = question.lower()
    assert question.endswith("?")
    assert "customer success associate" in lower_question
    assert "resolve onboarding blockers" in lower_question or "improve customer retention" in lower_question
    assert "communication" in lower_question or "documentation" in lower_question or "stakeholder coordination" in lower_question
    assert "retention" in answer.lower() or "onboarding" in answer.lower()


def test_generate_question_skill_curriculum_uses_clean_python_html_problem_solving_questions() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context=(
            "Role: Trainee Software Developer. Required skills include Python, HTML, and problem-solving."
        ),
        difficulty=1,
        role_title="Trainee Software Developer",
        required_skills=["Python", "HTML", "Problem-solving to sign a 36-month bond with a 2 lakh security deposit"],
        key_requirements=["Work on frontend and backend development tasks"],
        variation_seed="session-skill-curriculum",
    ))

    lower_question = question.lower()
    assert question.endswith("?")
    assert "bond" not in lower_question
    assert "deposit" not in lower_question
    assert (
        "python" in lower_question
        or "html" in lower_question
        or "problem statement" in lower_question
    )
    assert len(answer.split()) >= 6


def test_generate_question_rejects_truncated_fragment_prompt() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, _answer = _run(engine.generate_question(
        context="Q1: What is until yo? Answer: We put the spotlight on you and will not be satisfied until you are.",
        difficulty=1,
    ))

    assert question.endswith("?")
    assert "until yo" not in question.lower()


def test_generate_question_prioritizes_jd_resume_skill_overlap() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context="Campus drive process and eligibility criteria are listed in this section.",
        difficulty=1,
        role_title="Software Developer",
        required_skills=["Python", "SQL", "Communication"],
        resume_skills=["Python", "Java"],
        key_requirements=["Build backend services and APIs"],
        variation_seed="overlap-session",
    ))

    assert question.endswith("?")
    lowered = question.lower()
    assert "java" not in lowered
    assert "python" in lowered or "sql" in lowered or "communication" in lowered
    assert len(answer.split()) >= 4


def test_generate_question_jd_mode_avoids_resume_only_skill_detours() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context=(
            "L1 Technical Support role requires handling customer queries, "
            "ticket updates, and troubleshooting network and Windows issues."
        ),
        difficulty=1,
        role_title="Technical Customer Support",
        required_skills=["Troubleshooting", "Customer Support", "Communication"],
        resume_skills=["Python", "HTML"],
        key_requirements=["Handle customer tickets and issue diagnosis"],
        input_type="jd",
        variation_seed="jd-no-resume-detour",
    ))

    lowered = question.lower()
    assert question.endswith("?")
    assert "python" not in lowered
    assert "html" not in lowered
    assert "troubleshooting" in lowered or "customer support" in lowered or "communication" in lowered
    assert len(answer.split()) >= 4


def test_text_mentions_focus_skill_blocks_off_skill_compensation_question() -> None:
    engine = QuestionEngine()

    assert not engine.text_mentions_focus_skill(
        "What is the gross monthly package after training completion?",
        ["Python", "SQL", "HTML"],
    )


def test_text_mentions_focus_skill_accepts_focus_skill_question() -> None:
    engine = QuestionEngine()

    assert engine.text_mentions_focus_skill(
        "How would a trainee software developer apply SQL in a project?",
        ["Python", "SQL", "HTML"],
    )


def test_sanitize_requirement_focus_rejects_eligibility_marks_line() -> None:
    engine = QuestionEngine()

    assert engine._sanitize_requirement_focus("minimum 75% marks throughout board exams and graduation") == ""


def test_contains_non_skill_noise_detects_marks_and_bond_terms() -> None:
    engine = QuestionEngine()

    assert engine._contains_non_skill_noise("How should a candidate maintain 75% marks and bond compliance?")


def test_generate_question_resume_input_type_asks_experience_based_question() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, _answer = _run(engine.generate_question(
        context="Candidate has project experience with Python and FastAPI in internship.",
        difficulty=1,
        role_title="Trainee Software Developer",
        required_skills=["Python", "FastAPI"],
        resume_skills=["Python", "FastAPI"],
        input_type="resume",
        variation_seed="resume-experience",
    ))

    lowered = question.lower()
    assert question.endswith("?")
    assert "resume" in lowered or "experience" in lowered or "where did you use" in lowered


def test_generate_question_jd_input_type_asks_requirement_based_question() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, _answer = _run(engine.generate_question(
        context="JD requires Python and SQL for backend development.",
        difficulty=1,
        role_title="Backend Developer",
        required_skills=["Python", "SQL"],
        input_type="jd",
        variation_seed="jd-requirement",
    ))

    lowered = question.lower()
    assert question.endswith("?")
    assert "what is" in lowered or "core concepts" in lowered or "commonly used" in lowered


def test_generate_question_does_not_inject_marks_requirement_into_question() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, _answer = _run(engine.generate_question(
        context="General hiring details are listed.",
        difficulty=2,
        role_title="Trainee Software Developer",
        required_skills=["Python"],
        key_requirements=["minimum 75% marks throughout board exams and graduation"],
        resume_skills=["Python"],
        input_type="jd",
        variation_seed="marks-filter",
    ))

    lowered = question.lower()
    assert "marks" not in lowered
    assert "graduation" not in lowered
    assert "percentage" not in lowered


def test_extract_skill_hints_from_text_detects_known_skills() -> None:
    engine = QuestionEngine()

    hints = engine.extract_skill_hints_from_text(
        "JD requires Python, SQL, and Git with API debugging for backend support."
    )

    lowered = {item.lower() for item in hints}
    assert "python" in lowered
    assert "sql" in lowered
    assert "git" in lowered


def test_generate_question_strict_skill_mode_raises_for_non_skill_chunk() -> None:
    engine = QuestionEngine()
    engine.model = None

    with pytest.raises(RuntimeError, match="skill-focused question"):
        _run(engine.generate_question(
            context="Compensation details include fixed CTC, shift timing, and notice period.",
            difficulty=1,
            role_title="",
            required_skills=[],
            strict_skill_mode=True,
            input_type="jd",
        ))


def test_generate_question_strict_skill_mode_uses_role_defaults_when_available() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context="Compensation details include fixed CTC, shift timing, and notice period.",
        difficulty=1,
        role_title="Technical Customer Support",
        required_skills=[],
        strict_skill_mode=True,
        input_type="jd",
    ))

    lowered = question.lower()
    assert question.endswith("?")
    assert (
        "troubleshooting" in lowered
        or "ticketing" in lowered
        or "communication" in lowered
        or "customer support" in lowered
    )
    assert len(answer.split()) >= 5


def test_generate_question_strict_mode_can_use_profile_skills_fallback() -> None:
    engine = QuestionEngine()
    engine.model = None

    question, answer = _run(engine.generate_question(
        context="General company overview and hiring process information.",
        difficulty=1,
        role_title="Backend Developer",
        required_skills=["Python", "SQL"],
        input_type="jd",
        strict_skill_mode=True,
        variation_seed="strict-profile-fallback",
    ))

    lowered = question.lower()
    assert question.endswith("?")
    assert "python" in lowered or "sql" in lowered
    assert len(answer.split()) >= 5


def test_extract_skill_hints_from_skill_list_sentence() -> None:
    engine = QuestionEngine()

    hints = engine.extract_skill_hints_from_text(
        "Required Skills: HTML, CSS, JavaScript, SQL, OOPS, Git"
    )

    lowered = {item.lower() for item in hints}
    assert "html" in lowered
    assert "css" in lowered
    assert "javascript" in lowered
    assert "sql" in lowered
    assert "oop" in lowered or "oops" in lowered


def test_infer_role_skill_defaults_for_support_role() -> None:
    engine = QuestionEngine()

    defaults = engine.infer_role_skill_defaults("Technical Customer Support Associate")
    lowered = {item.lower() for item in defaults}

    assert "troubleshooting" in lowered
    assert "communication" in lowered
