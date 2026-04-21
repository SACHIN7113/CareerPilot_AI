import asyncio
import json

from app.config import settings
from app.services.analysis_engine import AnalysisEngine


class SyncAnalysisEngine(AnalysisEngine):
    def analyze_match(self, *, jd_text: str, resume_text: str, practice_answers: list[dict[str, str]] | None = None) -> dict:
        return asyncio.run(
            super().analyze_match(jd_text=jd_text, resume_text=resume_text, practice_answers=practice_answers)
        )

    def generate_hr_questions(self, *, jd_text: str, resume_text: str, count: int = 6) -> dict:
        return asyncio.run(super().generate_hr_questions(jd_text=jd_text, resume_text=resume_text, count=count))

    def evaluate_hr_answers(self, *, jd_text: str, resume_text: str, answers: list[dict[str, str]]) -> dict:
        return asyncio.run(super().evaluate_hr_answers(jd_text=jd_text, resume_text=resume_text, answers=answers))

    def generate_mcq_assessment(self, *, jd_text: str, count: int = 10) -> dict:
        return asyncio.run(super().generate_mcq_assessment(jd_text=jd_text, count=count))

    def generate_resume_mcq_assessment(self, *, resume_text: str, jd_text: str = "", count: int = 10) -> dict:
        return asyncio.run(super().generate_resume_mcq_assessment(resume_text=resume_text, jd_text=jd_text, count=count))

    def generate_resume_questions(self, *, resume_text: str, jd_text: str = "", count: int = 10) -> dict:
        return asyncio.run(super().generate_resume_questions(resume_text=resume_text, jd_text=jd_text, count=count))

    def evaluate_resume_answers(self, *, jd_text: str, resume_text: str, answers: list[dict[str, str]]) -> dict:
        return asyncio.run(super().evaluate_resume_answers(jd_text=jd_text, resume_text=resume_text, answers=answers))


# Keep tests deterministic and independent of external LLM quota/network.
settings.analysis_llm_refinement = False


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.text = json.dumps(payload)


class _FakeModel:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def generate_content(self, _prompt: str, generation_config=None):
        _ = generation_config
        return _FakeResponse(self.payload)


class _FailingModel:
    def generate_content(self, _prompt: str, generation_config=None):
        _ = generation_config
        raise AssertionError("LLM should not be called in fast mode")


def test_analyze_match_returns_structured_output() -> None:
    engine = SyncAnalysisEngine()
    engine.model = _FakeModel(
        {
            "overall_score": 82,
            "verdict": "Strong Match",
            "matched_keywords": ["python", "fastapi", "docker", "rest api"],
            "missing_keywords": ["kubernetes"],
            "jd_key_points": ["Backend role with API and cloud expectations."],
            "resume_highlights": ["Built FastAPI services and deployed with Docker."],
            "recommendations": ["Add Kubernetes production examples."],
            "summary": "The resume aligns strongly with core backend requirements and has one notable infrastructure gap.",
        }
    )

    jd = (
        "We need a Python backend developer with FastAPI, SQL, Docker, and REST API experience. "
        "Candidate should write unit tests and understand cloud deployment."
    )
    resume = (
        "Built FastAPI services in Python with PostgreSQL and Docker. "
        "Implemented REST APIs, wrote pytest unit tests, and deployed apps to cloud platforms."
    )

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    assert 0 <= result["overall_score"] <= 100
    assert result["verdict"] in {"Strong Match", "Moderate Match", "Low Match"}
    assert isinstance(result["matched_keywords"], list)
    assert isinstance(result["missing_keywords"], list)
    assert isinstance(result["resume_role_keywords"], list)
    assert isinstance(result["critical_missing_skills"], list)
    assert isinstance(result["recommendations"], list)
    assert isinstance(result["uses_llm"], bool)
    assert result["uses_rag"] is True


def test_analyze_match_detects_missing_jd_skills() -> None:
    engine = SyncAnalysisEngine()
    engine.model = _FakeModel(
        {
            "overall_score": 44,
            "verdict": "Low Match",
            "matched_keywords": ["python"],
            "missing_keywords": ["kubernetes", "terraform", "azure devops"],
            "jd_key_points": ["Infrastructure-heavy role."],
            "resume_highlights": ["Python and Django experience."],
            "recommendations": ["Add infra deployment experience and tools."],
            "summary": "The resume is missing several mandatory DevOps capabilities from the JD.",
        }
    )

    jd = "Role requires Kubernetes, Terraform, and Azure DevOps for production infrastructure."
    resume = "Experienced in Python, Django, and SQL application development."

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    lowered_missing = {item.lower() for item in result["missing_keywords"]}
    lowered_critical = {item.lower() for item in result["critical_missing_skills"]}
    assert any("kubernetes" in item for item in lowered_missing.union(lowered_critical))
    assert any("kubernetes" in item for item in lowered_critical)


def test_analyze_match_works_without_llm_model() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._candidate_model_names = lambda: []

    previous_llm_refinement = settings.analysis_llm_refinement
    try:
        settings.analysis_llm_refinement = False
        result = engine.analyze_match(
            jd_text="Role needs Python and SQL with API development.",
            resume_text="Python and SQL experience with REST API development.",
        )
    finally:
        settings.analysis_llm_refinement = previous_llm_refinement

    assert 0 <= result["overall_score"] <= 100
    assert result["uses_llm"] is False


def test_analyze_match_filters_noisy_critical_terms() -> None:
    engine = SyncAnalysisEngine()
    engine.model = _FakeModel(
        {
            "overall_score": 40,
            "verdict": "Low Match",
            "critical_missing_skills": ["hands-on", "exposure", "give", "kubernetes"],
            "matched_keywords": ["python"],
            "missing_keywords": ["kubernetes", "docker"],
            "jd_key_points": ["Must have hands-on exposure to Kubernetes and Docker in production."],
            "resume_highlights": ["Python backend development."],
            "recommendations": ["Add Kubernetes and Docker project evidence."],
            "summary": "Critical infrastructure requirements are missing.",
        }
    )

    jd = "Must have hands-on exposure to Kubernetes and Docker for production deployments."
    resume = "Worked on Python backend APIs and SQL databases."

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    lowered_critical = {item.lower() for item in result["critical_missing_skills"]}
    assert "kubernetes" in lowered_critical
    assert "hands-on" not in lowered_critical
    assert "exposure" not in lowered_critical
    assert "give" not in lowered_critical


def test_analyze_match_reconciles_matched_and_missing_skill_variants() -> None:
    engine = SyncAnalysisEngine()
    engine.model = _FakeModel(
        {
            "overall_score": 68,
            "verdict": "Moderate Match",
            "critical_missing_skills": ["problem-solving", "kubernetes"],
            "matched_keywords": ["problem solving", "python"],
            "missing_keywords": ["problem-solving", "kubernetes", "docker"],
            "jd_key_points": ["Need problem-solving and Kubernetes skills."],
            "resume_highlights": ["Strong problem solving in projects."],
            "recommendations": ["Add Kubernetes and Docker deployment evidence."],
            "summary": "Good base profile with infra gaps.",
        }
    )

    jd = "Must have strong problem-solving, Kubernetes, and Docker experience."
    resume = "Candidate has strong problem solving and Python API development experience."

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    lowered_matched = {item.lower() for item in result["matched_keywords"]}
    lowered_missing = {item.lower() for item in result["missing_keywords"]}
    lowered_critical = {item.lower() for item in result["critical_missing_skills"]}

    assert any("problem" in item for item in lowered_matched)
    assert not any("problem" in item for item in lowered_missing)
    assert not any("problem" in item for item in lowered_critical)


def test_analyze_match_uses_must_have_requirements_and_intro_evidence() -> None:
    engine = SyncAnalysisEngine()
    engine.model = _FakeModel(
        {
            "overall_score": 62,
            "verdict": "Moderate Match",
            "critical_missing_skills": [],
            "matched_keywords": [],
            "missing_keywords": [],
            "jd_key_points": ["QA intern role with must-have testing requirements."],
            "resume_highlights": ["Internship details mention manual/API testing and test cases."],
            "recommendations": ["Add automation testing project evidence."],
            "summary": "Baseline result.",
        }
    )

    jd = (
        "Must-Have Requirements\n"
        "- Strong knowledge of Manual Testing concepts\n"
        "- Hands-on experience in writing test cases\n"
        "- Basic understanding of Automation Testing and API Testing\n"
    )
    resume = (
        "In my internship intro, I performed manual testing on web apps, wrote structured test cases, "
        "and validated REST APIs using Postman."
    )

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    lowered_critical = {item.lower() for item in result["critical_missing_skills"]}
    assert any("automation" in item for item in lowered_critical)
    assert not any("manual testing" in item for item in lowered_critical)
    assert not any("test case" in item for item in lowered_critical)
    assert not any("api testing" in item for item in lowered_critical)


def test_generate_hr_questions_returns_fixed_bank() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None

    jd = "Any JD text should be ignored for HR practice question generation."
    resume = "Any resume text should be ignored for HR practice question generation."

    result = engine.generate_hr_questions(jd_text=jd, resume_text=resume, count=8)

    expected_questions = [
        "Tell me about yourself.",
        "Why do you want this role?",
        "What do you know about our company?",
        "Why should we hire you, and what are your strengths and weaknesses?",
        "How do you handle pressure or deadlines?",
        "Where do you see yourself in the next 3 to 5 years?",
        "Are you comfortable with shift, relocation, or bond requirements?",
        "Do you have any questions for us?",
    ]

    assert result["role_track"] == "HR Interview Round"
    assert [item["question"] for item in result["questions"]] == expected_questions


def test_generate_hr_questions_not_dependent_on_jd_or_resume() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None

    qa_result = engine.generate_hr_questions(
        jd_text="QA engineer role with manual testing and API testing",
        resume_text="Backend Python profile",
        count=6,
    )
    sales_result = engine.generate_hr_questions(
        jd_text="Sales executive role with CRM and lead generation",
        resume_text="Data analyst profile",
        count=6,
    )

    assert qa_result["questions"] == sales_result["questions"]
    assert len(qa_result["questions"]) == 6


def test_analyze_match_keeps_strong_technical_profile_above_low_band() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._build_rag_context = lambda **_kwargs: {"jd_context": "", "resume_context": "", "uses_rag": False}
    engine._semantic_similarity = lambda _jd, _resume: 0.82

    jd = (
        "Software Engineer role. Must have Python, FastAPI, SQL, Docker, AWS, Kubernetes, and CI/CD experience."
    )
    resume = (
        "Built Python FastAPI services with SQL and Docker in production. "
        "Deployed microservices on AWS and maintained CI/CD pipelines for releases."
    )

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    assert result["overall_score"] >= 60
    assert result["verdict"] in {"Strong Match", "Moderate Match"}


def test_analyze_match_returns_low_for_nontechnical_resume_on_technical_jd() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._build_rag_context = lambda **_kwargs: {"jd_context": "", "resume_context": "", "uses_rag": False}
    engine._semantic_similarity = lambda _jd, _resume: 0.20

    jd = "Need Software Engineer with Python, FastAPI, SQL, Docker, AWS, and Kubernetes."
    resume = "Experienced in customer support, sales follow-ups, communication, and onboarding workflows."

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    assert result["overall_score"] <= 45
    assert result["verdict"] == "Low Match"


def test_analyze_match_treats_mysql_postgresql_as_alternative_requirement() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._build_rag_context = lambda **_kwargs: {"jd_context": "", "resume_context": "", "uses_rag": False}
    engine._semantic_similarity = lambda _jd, _resume: 0.75

    jd = "Must have Python, FastAPI, and MySQL/PostgreSQL experience for backend development."
    resume = "Developed Python FastAPI APIs with MySQL database and production REST integrations."

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    lowered_missing = {item.lower() for item in result["missing_keywords"]}
    lowered_critical = {item.lower() for item in result["critical_missing_skills"]}

    assert not any("postgresql" in item for item in lowered_missing)
    assert not any("postgresql" in item for item in lowered_critical)


def test_evaluate_hr_answers_falls_back_when_llm_fails() -> None:
    engine = SyncAnalysisEngine()
    engine.model = _FailingModel()
    engine._candidate_model_names = lambda: []

    previous_fast_mode = settings.analysis_fast_mode
    previous_llm_refinement = settings.analysis_llm_refinement
    try:
        settings.analysis_fast_mode = True
        settings.analysis_llm_refinement = True
        result = engine.evaluate_hr_answers(
            jd_text="Software Engineer role with Python and API development.",
            resume_text="Python backend developer with APIs and SQL.",
            answers=[
                {
                    "question_id": "q1",
                    "question": "Tell me about yourself.",
                    "answer": "I am a backend developer with two years of experience building Python APIs.",
                }
            ],
        )
    finally:
        settings.analysis_fast_mode = previous_fast_mode
        settings.analysis_llm_refinement = previous_llm_refinement

    assert result["overall_score"] >= 0
    assert len(result["answer_feedback"]) == 1
    assert result["uses_llm"] is False


def test_evaluate_hr_answers_marks_uses_llm_true_and_adds_resume_grounding() -> None:
    engine = SyncAnalysisEngine()
    engine.model = _FakeModel(
        {
            "overall_score": 72,
            "answer_feedback": [
                {
                    "question_id": "q1",
                    "question": "Why do you want this role?",
                    "submitted_answer": "I want this role to solve real customer problems.",
                    "score": 72,
                    "feedback": "Good motivation statement.",
                    "improved_answer": "I want this opportunity because it matches my interests and growth goals.",
                }
            ],
            "final_tips": ["Use one project example with measurable impact."],
        }
    )

    previous_llm_refinement = settings.analysis_llm_refinement
    try:
        settings.analysis_llm_refinement = True
        result = engine.evaluate_hr_answers(
            jd_text="Software Engineer role with Python, SQL, and API development.",
            resume_text="Built Python and SQL APIs in internship projects.",
            answers=[
                {
                    "question_id": "q1",
                    "question": "Why do you want this role?",
                    "answer": "I want this role to solve real customer problems.",
                }
            ],
        )
    finally:
        settings.analysis_llm_refinement = previous_llm_refinement

    improved = result["answer_feedback"][0]["improved_answer"].lower()
    assert result["uses_llm"] is True
    assert "based on your resume" in improved


def test_analyze_match_filters_llm_false_missing_for_alternative_skills() -> None:
    engine = SyncAnalysisEngine()
    engine.model = _FakeModel(
        {
            "overall_score": 48,
            "verdict": "Low Match",
            "critical_missing_skills": ["PostgreSQL"],
            "matched_keywords": ["python", "fastapi", "mysql"],
            "missing_keywords": ["PostgreSQL"],
            "jd_key_points": ["Need either MySQL or PostgreSQL for backend role."],
            "resume_highlights": ["Candidate has MySQL with FastAPI project work."],
            "recommendations": ["Highlight backend architecture outcomes clearly."],
            "summary": "Candidate has one DB mismatch.",
        }
    )
    engine._build_rag_context = lambda **_kwargs: {"jd_context": "", "resume_context": "", "uses_rag": False}
    engine._semantic_similarity = lambda _jd, _resume: 0.8

    jd = "Software Engineer role requiring Python, FastAPI, and MySQL/PostgreSQL for production backend systems."
    resume = "Built Python FastAPI APIs with MySQL database and deployed production backend services."

    previous_llm_refinement = settings.analysis_llm_refinement
    try:
        settings.analysis_llm_refinement = True
        result = engine.analyze_match(jd_text=jd, resume_text=resume)
    finally:
        settings.analysis_llm_refinement = previous_llm_refinement

    lowered_missing = {item.lower() for item in result["missing_keywords"]}
    lowered_critical = {item.lower() for item in result["critical_missing_skills"]}

    assert result["uses_llm"] is True
    assert not any("postgresql" in item for item in lowered_missing)
    assert not any("postgresql" in item for item in lowered_critical)


def test_compose_improved_answer_is_question_aware_for_intro_and_motivation() -> None:
    engine = SyncAnalysisEngine()

    intro = engine._compose_improved_answer(
        question="Tell me about yourself",
        answer="My name is Sachin Yadav. I am a recent BTech graduate with React and Python project experience.",
        role_track="Frontend Developer",
        required_skills=["react", "python", "sql"],
    )
    motivation = engine._compose_improved_answer(
        question="Why do you want this role?",
        answer="I want this role because I enjoy frontend development and solving real user problems.",
        role_track="Frontend Developer",
        required_skills=["react", "javascript", "css"],
    )

    assert "my name is" in intro.lower()
    assert "i want this opportunity" in motivation.lower()
    assert intro != motivation


def test_compose_improved_answer_is_question_aware_for_strengths_and_pressure() -> None:
    engine = SyncAnalysisEngine()

    strengths = engine._compose_improved_answer(
        question="Why should we hire you and tell me about your strengths and weaknesses?",
        answer="My strengths are quick learning and teamwork. My weakness is overthinking details sometimes.",
        role_track="Backend Developer",
        required_skills=["python", "fastapi", "sql"],
    )
    pressure = engine._compose_improved_answer(
        question="How do you handle pressure or deadlines?",
        answer="I stay calm, break tasks into parts, and prioritize based on impact.",
        role_track="Backend Developer",
        required_skills=["python", "api", "sql"],
    )

    assert "you should hire me" in strengths.lower()
    assert "weakness" in strengths.lower()
    assert "i handle pressure" in pressure.lower()
    assert strengths != pressure


def test_evaluate_hr_answers_uses_neutral_role_wording_in_improved_answer() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None

    result = engine.evaluate_hr_answers(
        jd_text="Software Engineer role for graduates with SQL, analytics, and testing exposure.",
        resume_text="Candidate profile includes SQL, Python, and QA internship tasks.",
        answers=[
            {
                "question_id": "q1",
                "question": "Why do you want this role?",
                "answer": "I like solving user problems and building practical software solutions.",
            }
        ],
    )

    improved = result["answer_feedback"][0]["improved_answer"].lower()
    assert "data analyst opportunity" not in improved
    assert "this opportunity" in improved


def test_extract_candidate_name_ignores_trailing_noise() -> None:
    engine = SyncAnalysisEngine()
    name = engine._extract_candidate_name(
        "My name is Sachin Yadav so currently I am pursuing better technology and learning full stack development."
    )
    assert name == "Sachin Yadav"


def test_analyze_match_includes_resume_role_keywords() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._build_rag_context = lambda **kwargs: {
        "jd_context": kwargs["jd_text"],
        "resume_context": kwargs["resume_text"],
        "uses_rag": True,
    }
    engine._semantic_similarity = lambda _jd, _resume: 0.75

    jd = "Software Engineer role requires Python, FastAPI, SQL, Docker, and REST API development."
    resume = "Built Python FastAPI APIs using SQL and Docker for backend web products."

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    lowered = {item.lower() for item in result["resume_role_keywords"]}
    assert any("python" in item for item in lowered)
    assert any("fastapi" in item or "api" in item for item in lowered)


def test_analyze_match_excludes_eligibility_terms_from_skill_lists() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._build_rag_context = lambda **kwargs: {
        "jd_context": kwargs["jd_text"],
        "resume_context": kwargs["resume_text"],
        "uses_rag": True,
    }
    engine._semantic_similarity = lambda _jd, _resume: 0.70

    jd = (
        "Eligibility: B.Tech CSE graduate. Required: Python, SQL, and API development for software engineer role."
    )
    resume = (
        "Final year B.Tech CSE student with Python SQL API project experience and backend internship exposure."
    )

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    matched = {item.lower() for item in result["matched_skills"]}
    role_keywords = {item.lower() for item in result["resume_role_keywords"]}

    assert not any("btech" in item or "cse" in item or "graduate" in item for item in matched)
    assert not any("btech" in item or "cse" in item or "graduate" in item for item in role_keywords)


def test_analyze_match_critical_skills_not_duplicated_in_missing_skills() -> None:
    engine = SyncAnalysisEngine()
    engine.model = _FakeModel(
        {
            "overall_score": 52,
            "verdict": "Moderate Match",
            "critical_missing_skills": ["postgresql"],
            "matched_keywords": ["python", "fastapi", "sql"],
            "missing_keywords": ["postgresql", "oop concepts"],
            "jd_key_points": ["Need backend database readiness."],
            "resume_highlights": ["Has Python/FastAPI project work."],
            "recommendations": ["Add database-specific production evidence."],
            "summary": "One important database gap remains.",
        }
    )
    engine._build_rag_context = lambda **_kwargs: {"jd_context": "", "resume_context": "", "uses_rag": False}
    engine._semantic_similarity = lambda _jd, _resume: 0.65

    jd = "Software Engineer role requires Python, FastAPI, SQL and PostgreSQL."
    resume = "Built Python FastAPI APIs and SQL-backed features in internship projects."

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    missing_keys = {item.lower() for item in result["missing_skills"]}
    critical_keys = {item.lower() for item in result["critical_missing_skills"]}
    assert critical_keys
    assert critical_keys.issubset(missing_keys)


def test_analyze_match_filters_llm_false_sql_missing_when_mysql_present() -> None:
    engine = SyncAnalysisEngine()
    engine.model = _FakeModel(
        {
            "overall_score": 60,
            "verdict": "Moderate Match",
            "critical_missing_skills": ["SQL"],
            "matched_keywords": ["python", "mysql", "fastapi"],
            "missing_keywords": ["SQL"],
            "jd_key_points": ["Need SQL and backend API skills."],
            "resume_highlights": ["MySQL-backed API project experience."],
            "recommendations": ["Improve backend impact descriptions."],
            "summary": "Candidate lacks explicit SQL.",
        }
    )
    engine._build_rag_context = lambda **kwargs: {
        "jd_context": kwargs["jd_text"],
        "resume_context": kwargs["resume_text"],
        "uses_rag": True,
    }
    engine._semantic_similarity = lambda _jd, _resume: 0.78

    jd = "Software Engineer role requires Python, FastAPI, SQL, and MySQL/PostgreSQL."
    resume = "Built Python FastAPI services with MySQL database integrations in production-like projects."

    result = engine.analyze_match(jd_text=jd, resume_text=resume)

    lowered_missing = {item.lower() for item in result["missing_skills"]}
    lowered_critical = {item.lower() for item in result["critical_missing_skills"]}
    assert not any("sql" == item or "sql" in item for item in lowered_missing)
    assert not any("sql" == item or "sql" in item for item in lowered_critical)


def test_analyze_match_falls_back_when_llm_refinement_is_unavailable() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._candidate_model_names = lambda: []

    previous_llm_refinement = settings.analysis_llm_refinement
    try:
        settings.analysis_llm_refinement = True
        result = engine.analyze_match(
            jd_text="Need Python backend engineer with SQL.",
            resume_text="Python and SQL project experience.",
        )
        assert isinstance(result, dict)
        assert result["uses_llm"] is False
        assert any(
            "heuristic analysis was used" in str(item).lower()
            for item in result.get("recommendations", [])
        )
    finally:
        settings.analysis_llm_refinement = previous_llm_refinement


def test_generate_mcq_assessment_returns_requested_count_without_llm() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._candidate_model_names = lambda: []

    result = engine.generate_mcq_assessment(
        jd_text=(
            "Backend engineer role requires Python, FastAPI, SQL, Docker, API design, "
            "and cloud deployment readiness."
        ),
        count=20,
    )

    questions = result["questions"]
    assert len(questions) == 20
    assert all(len(item["options"]) == 4 for item in questions)
    assert all(0 <= int(item["correct_option_index"]) <= 3 for item in questions)


def test_generate_mcq_assessment_uses_llm_when_payload_is_valid() -> None:
    engine = SyncAnalysisEngine()
    engine.model = _FakeModel(
        {
            "questions": [
                {
                    "question": "Which skill is required in this JD for backend API development",
                    "options": ["FastAPI", "Video Editing", "Payroll", "Warehouse Operations"],
                    "correct_option_index": 0,
                },
                {
                    "question": "Which database capability is called out in the JD",
                    "options": ["Graphic Design", "SQL", "Travel Planning", "Legal Drafting"],
                    "correct_option_index": 1,
                },
            ]
        }
    )
    engine._candidate_model_names = lambda: []

    result = engine.generate_mcq_assessment(
        jd_text="Role requires FastAPI and SQL for backend service development.",
        count=10,
    )

    questions = result["questions"]
    assert len(questions) == 10
    assert questions[0]["question"].endswith("?")
    assert questions[0]["options"][0] == "FastAPI"


def test_generate_mcq_assessment_detects_management_track_for_management_jd() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._candidate_model_names = lambda: []

    result = engine.generate_mcq_assessment(
        jd_text=(
            "Campus drive for Operations Manager role. Required skills include stakeholder management, "
            "KPI tracking, planning, reporting, and team coordination."
        ),
        count=10,
    )

    assert len(result["questions"]) == 10
    assert any("management" in item["question"].lower() for item in result["questions"])


def test_generate_mcq_assessment_detects_technical_track_for_software_jd() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._candidate_model_names = lambda: []

    result = engine.generate_mcq_assessment(
        jd_text=(
            "Software Engineer role requiring Python, FastAPI, SQL, API development, and Docker for production systems."
        ),
        count=10,
    )

    assert len(result["questions"]) == 10
    assert any("technical role" in item["question"].lower() or "software/technical" in item["question"].lower() for item in result["questions"])


def test_generate_resume_mcq_assessment_returns_requested_count_without_llm() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._candidate_model_names = lambda: []

    result = engine.generate_resume_mcq_assessment(
        resume_text=(
            "Built projects with Python, FastAPI, SQL, Docker, JavaScript, and REST APIs. "
            "Used Git and unit tests in internships."
        ),
        count=20,
    )

    questions = result["questions"]
    assert len(questions) == 20
    assert all(len(item["options"]) == 4 for item in questions)
    assert all(0 <= int(item["correct_option_index"]) <= 3 for item in questions)


def test_generate_resume_mcq_assessment_management_resume_uses_management_wording() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._candidate_model_names = lambda: []

    result = engine.generate_resume_mcq_assessment(
        resume_text=(
            "Operations manager with stakeholder management, KPI reporting, team coordination, "
            "planning, and execution experience."
        ),
        count=10,
    )

    assert len(result["questions"]) == 10
    assert any("management" in item["question"].lower() for item in result["questions"])


def test_generate_resume_questions_returns_descriptive_question_set() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._candidate_model_names = lambda: []

    result = engine.generate_resume_questions(
        resume_text=(
            "Built Python, FastAPI, SQL, and Docker projects. Worked on REST APIs and testing in internship."
        ),
        jd_text="Software engineer role for backend development and API delivery.",
        count=10,
    )

    assert len(result["questions"]) == 10
    assert all("options" not in item for item in result["questions"])
    assert all("focus" in item for item in result["questions"])


def test_evaluate_resume_answers_returns_feedback_and_improved_answer() -> None:
    engine = SyncAnalysisEngine()
    engine.model = None
    engine._candidate_model_names = lambda: []

    result = engine.evaluate_resume_answers(
        jd_text="Need Python backend developer with API and SQL skills.",
        resume_text="Built Python FastAPI APIs with SQL and Docker in internship projects.",
        answers=[
            {
                "question_id": "q1",
                "question": "Explain a real project where you used Python and SQL.",
                "answer": "I built an API service in Python with SQL schema design and query optimization.",
            }
        ],
    )

    assert result["overall_score"] >= 0
    assert result["answer_feedback"]
    item = result["answer_feedback"][0]
    assert item["improved_answer"]
    assert isinstance(item["is_correct"], bool)


def test_generate_ats_resume_handles_none_missing_skills_added() -> None:
    engine = SyncAnalysisEngine()

    async def _fake_llm_generate_ats_resume(**_kwargs):
        return {
            "ats_resume": (
                "PROFESSIONAL SUMMARY\n"
                "Backend-focused fresher with hands-on API and SQL project exposure.\n\n"
                "WORK EXPERIENCE\n"
                "Internship experience in backend development.\n\n"
                "PROJECTS\n"
                "Built FastAPI services with SQL integration.\n\n"
                "SKILLS\n"
                "Python, FastAPI, SQL\n"
            ),
            "missing_skills_added": None,
            "improvement_notes": ["Aligned resume wording with JD requirements."],
        }

    engine.model = object()
    engine._llm_generate_ats_resume = _fake_llm_generate_ats_resume
    engine._is_resume_layout_malformed = lambda _text: False

    previous_llm_refinement = settings.analysis_llm_refinement
    try:
        settings.analysis_llm_refinement = True
        result = asyncio.run(
            engine.generate_ats_resume_async(
                jd_text=(
                    "Backend Software Engineer role requiring Python, FastAPI, SQL, and API development. "
                    "Candidate should be able to build production-ready web services."
                ),
                resume_text=(
                    "Recent graduate with internship exposure in Python backend development. "
                    "Built FastAPI APIs, integrated SQL queries, and delivered REST services in projects."
                ),
                missing_skills=["Docker", "Testing"],
                target_role="Backend Software Engineer",
                custom_prompt="Keep the resume ATS-friendly and concise.",
            )
        )
    finally:
        settings.analysis_llm_refinement = previous_llm_refinement

    assert isinstance(result.get("missing_skills_added"), list)
    assert result["target_role"] == "Backend Software Engineer"


def test_generate_ats_resume_renders_template_payload_and_sanitizes_output() -> None:
    engine = SyncAnalysisEngine()

    async def _fake_llm_generate_ats_resume(**_kwargs):
        return {
            "summary": "Delivered delivered backend features for job-aligned applications",
            "experience": [
                "Delivered APIs for resume analysis workflows",
                "Delivered APIs for resume analysis workflows",
            ],
            "projects": [
                {
                    "name": "CareerPilot AI",
                    "bullets": [
                        "Delivered end-to-end resume screening pipeline",
                        "Designed a clean React and FastAPI workflow",
                    ],
                }
            ],
            "skills": ["Python", "FastAPI", "MongoDB", "REST API"],
            "education": ["B.Tech Computer Science Engineering, Medi-Caps University"],
            "missing_skills_added": ["Docker"],
            "improvement_notes": ["Aligned the rewrite with ATS structure."],
        }

    engine.model = object()
    engine._llm_generate_ats_resume = _fake_llm_generate_ats_resume

    previous_llm_refinement = settings.analysis_llm_refinement
    try:
        settings.analysis_llm_refinement = True
        result = asyncio.run(
            engine.generate_ats_resume_async(
                jd_text=(
                    "Backend role requiring Python, FastAPI, MongoDB, and API development with strong project ownership."
                ),
                resume_text=(
                    "Worked on full-stack internship projects using Python, React, FastAPI, and MongoDB with practical API usage."
                ),
                missing_skills=["Docker"],
                target_role="Backend Engineer",
                custom_prompt="Use template JSON format.",
            )
        )
    finally:
        settings.analysis_llm_refinement = previous_llm_refinement

    ats_resume = str(result.get("ats_resume") or "")
    assert result.get("uses_llm") is True
    assert "PROFESSIONAL SUMMARY" in ats_resume
    assert "WORK EXPERIENCE" in ats_resume
    assert "PROJECTS" in ats_resume
    assert "SKILLS" in ats_resume
    assert "delivered" not in ats_resume.lower()
    assert ats_resume.lower().count("developed apis for resume analysis workflows.") <= 1


def test_generate_ats_resume_formats_dict_education_without_python_repr() -> None:
    engine = SyncAnalysisEngine()

    async def _fake_llm_generate_ats_resume(**_kwargs):
        return {
            "summary": "Strong backend-focused candidate with practical project experience.",
            "experience": [
                {
                    "role": "Project Intern",
                    "company": "47Billion",
                    "duration": "06/2025 - 08/2025",
                    "bullets": ["Developed backend APIs and improved performance"],
                }
            ],
            "projects": [
                {
                    "name": "CareerPilot AI",
                    "bullets": ["Built an ATS and skill-gap analyzer platform"],
                }
            ],
            "skills": ["Python", "FastAPI", "MongoDB"],
            "education": [
                {
                    "institution": "Medi-caps University",
                    "degree": "Bachelor of Technology in Computer Science and Engineering",
                    "cgpa": "7.79",
                    "duration": "2022 - 2026",
                }
            ],
            "missing_skills_added": [],
            "improvement_notes": ["Polished format and language."],
        }

    engine.model = object()
    engine._llm_generate_ats_resume = _fake_llm_generate_ats_resume

    previous_llm_refinement = settings.analysis_llm_refinement
    try:
        settings.analysis_llm_refinement = True
        result = asyncio.run(
            engine.generate_ats_resume_async(
                jd_text="Backend role requiring Python, FastAPI, and MongoDB.",
                resume_text="SACHIN YADAV yadavsaching7113@gmail.com +91-9753711397",
                missing_skills=["Docker"],
                target_role="Backend Engineer",
                custom_prompt="Keep original data and polish language only.",
            )
        )
    finally:
        settings.analysis_llm_refinement = previous_llm_refinement

    ats_resume = str(result.get("ats_resume") or "")
    assert "{'institution'" not in ats_resume
    assert "Bachelor of Technology in Computer Science and Engineering" in ats_resume
    assert "Medi-caps University" in ats_resume
