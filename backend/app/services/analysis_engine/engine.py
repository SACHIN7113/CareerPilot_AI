import re
from collections import Counter

from app.config.settings import settings
from app.services.document_parser import chunk_text
from app.services.embedding_service import _cosine_similarity_sync as cosine_similarity, embedding_service
from app.services.gemini_service import (
    _extract_text_sync as extract_text,
    _get_model_sync as get_model,
    _parse_json_response_sync as parse_json_response,
)

from .match_service import AnalysisMatchMixin
from .assessment_service import AnalysisAssessmentMixin
from .resume_service import AnalysisResumeMixin
from .hr_service import AnalysisHrMixin


class AnalysisEngine(AnalysisMatchMixin, AnalysisAssessmentMixin, AnalysisResumeMixin, AnalysisHrMixin):
    _RAG_CHUNK_SIZE = 900
    _RAG_CHUNK_OVERLAP = 120
    _RAG_JD_TOP_K = 6
    _RAG_RESUME_TOP_K = 8

    _STOP_WORDS = {
        "about",
        "after",
        "also",
        "and",
        "are",
        "can",
        "for",
        "from",
        "have",
        "into",
        "just",
        "more",
        "most",
        "not",
        "only",
        "other",
        "over",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "very",
        "was",
        "were",
        "will",
        "with",
        "your",
    }

    _SKILL_PHRASES = {
        "machine learning",
        "deep learning",
        "data analysis",
        "data structures",
        "system design",
        "object oriented programming",
        "problem solving",
        "unit testing",
        "api development",
        "cloud computing",
        "natural language processing",
        "computer vision",
        "sql query",
        "rest api",
    }

    _CANONICAL_SKILL_PATTERNS = {
        "sql": r"\bsql\b|\bmysql\b|\bpostgres(?:ql)?\b|\bsqlite\b|\bmariadb\b|\bms\s*sql\b",
        "manual testing": r"\bmanual\s+test(?:ing)?\b",
        "test case design": r"\btest\s+case(?:s)?\b|\btest\s+scenari(?:o|os)\b",
        "api testing": r"\bapi\s+test(?:ing)?\b|\brest\s+api\b|\bpostman\b",
        "automation testing": r"\bautomation\s+test(?:ing)?\b|\bselenium\b|\bcypress\b|\bplaywright\b|\btestng\b",
        "bug reporting": r"\bbug\s+report(?:ing)?\b|\bdefect\s+tracking\b|\bjira\b",
        "problem solving": r"\bproblem[-\s]?solv(?:ing|e)\b",
        "troubleshooting": r"\btroubleshoot(?:ing)?\b",
        "customer onboarding": r"\bcustomer\s+onboarding\b|\bonboarding\b",
        "real-time support": r"\breal[-\s]?time\b.*\bsupport\b|\bsupport\b.*\breal[-\s]?time\b",
        "btech degree": r"\bb\.?\s*tech\b|\bbtech\b",
        "computer science degree": r"\bcomputer\s+science\b|\bcse\b|\bcs\s*/\s*it\b|\bcsit\b",
        "mcp server": r"\bmcp\s+server\b",
        "communication skills": r"\bcommunication\s+skills?\b|\binterpersonal\s+skills?\b",
        "qa internship experience": r"\bqa\s+internship\b|\binternship\s+experience\b",
    }

    _REQUIRED_SECTION_MARKERS = (
        "must-have",
        "must have",
        "requirements",
        "required",
        "skills required",
    )

    _SECTION_BREAK_MARKERS = (
        "what will make you stand out",
        "preferred",
        "mindset",
        "about the job",
    )

    _CRITICAL_NOISE_TERMS = {
        "give",
        "must",
        "required",
        "mandatory",
        "essential",
        "need",
        "needs",
        "experience",
        "exposure",
        "hands-on",
        "hands on",
        "candidate",
        "role",
        "position",
        "job",
        "company",
        "support",
        "customer",
        "environment",
        "flexibility",
        "onboarding",
        "modern",
        "emerging",
        "must-have",
        "must have",
        "technologies",
        "technology",
        "build",
        "techdome",
    }

    _NON_SKILL_TERMS = {
        "btech",
        "b tech",
        "btech degree",
        "b tech degree",
        "btech cse",
        "b tech cse",
        "computer science",
        "computer science degree",
        "cse",
        "csit",
        "graduate",
        "fresher",
        "eligibility",
        "eligible",
        "team player",
        "immediate joiner",
        "relocation",
        "shift",
        "bond",
    }

    _TECH_HINT_TOKENS = {
        "python",
        "java",
        "javascript",
        "typescript",
        "html",
        "css",
        "react",
        "node",
        "fastapi",
        "django",
        "flask",
        "sql",
        "postgresql",
        "mysql",
        "mongodb",
        "docker",
        "kubernetes",
        "terraform",
        "aws",
        "azure",
        "gcp",
        "linux",
        "api",
        "rest",
        "ml",
        "machine",
        "learning",
        "nlp",
        "devops",
        "ci",
        "cd",
        "selenium",
        "postman",
        "jira",
        "cypress",
        "playwright",
        "testng",
        "testing",
        "qa",
        "bug",
        "troubleshooting",
        "git",
    }

    _GENERIC_NOISE_TOKENS = {
        "learning",
        "information",
        "work",
        "technical",
        "science",
        "data",
        "user",
        "platform",
        "role",
    }

    _MOTIVATION_TOKENS = {
        "grow",
        "learning",
        "learn",
        "impact",
        "contribute",
        "team",
        "mission",
        "challenge",
        "ownership",
        "build",
    }

    _SOFT_CORE_SKILLS = {
        "problem solving",
        "object oriented programming",
        "communication skills",
    }

    _ROLE_SKILL_MAP = {
        "Backend Developer": {
            "python",
            "java",
            "fastapi",
            "django",
            "flask",
            "api development",
            "rest api",
            "sql",
            "docker",
        },
        "QA Engineer": {
            "manual testing",
            "automation testing",
            "api testing",
            "bug reporting",
            "test case design",
            "selenium",
            "cypress",
            "jira",
        },
        "DevOps Engineer": {
            "docker",
            "kubernetes",
            "terraform",
            "aws",
            "azure",
            "gcp",
            "linux",
            "devops",
        },
        "Frontend Developer": {
            "javascript",
            "typescript",
            "react",
            "api development",
            "problem solving",
        },
        "Data Analyst": {
            "data analysis",
            "sql",
            "python",
            "machine learning",
            "problem solving",
        },
        "Technical Support Engineer": {
            "troubleshooting",
            "communication skills",
            "customer onboarding",
            "real-time support",
            "problem solving",
        },
        "Sales Executive": {
            "sales",
            "lead generation",
            "negotiation",
            "crm",
            "customer relationship",
            "pipeline",
            "communication skills",
        },
    }

    def __init__(self) -> None:
        self.model = get_model()

    async def analyze_match_async(
        self,
        *,
        jd_text: str,
        resume_text: str,
        practice_answers: list[dict[str, str]] | None = None,
    ) -> dict:
        return await self.analyze_match(
            jd_text=jd_text,
            resume_text=resume_text,
            practice_answers=practice_answers,
        )

    async def generate_hr_questions_async(self, *, jd_text: str, resume_text: str, count: int = 6) -> dict:
        return await self.generate_hr_questions(jd_text=jd_text, resume_text=resume_text, count=count)

    async def evaluate_hr_answers_async(
        self,
        *,
        jd_text: str,
        resume_text: str,
        answers: list[dict[str, str]],
    ) -> dict:
        return await self.evaluate_hr_answers(
            jd_text=jd_text,
            resume_text=resume_text,
            answers=answers,
        )

    async def generate_mcq_assessment_async(self, *, jd_text: str, count: int = 10) -> dict:
        return await self.generate_mcq_assessment(jd_text=jd_text, count=count)

    async def generate_resume_questions_async(self, *, resume_text: str, jd_text: str = "", count: int = 10) -> dict:
        return await self.generate_resume_questions(
            resume_text=resume_text,
            jd_text=jd_text,
            count=count,
        )

    async def evaluate_resume_answers_async(
        self,
        *,
        jd_text: str,
        resume_text: str,
        answers: list[dict[str, str]],
    ) -> dict:
        return await self.evaluate_resume_answers(
            jd_text=jd_text,
            resume_text=resume_text,
            answers=answers,
        )

    async def generate_ats_resume_async(
        self,
        *,
        jd_text: str,
        resume_text: str,
        missing_skills: list[str] | None = None,
        target_role: str = "",
        custom_prompt: str = "",
    ) -> dict:
        return await self.generate_ats_resume(
            jd_text=jd_text,
            resume_text=resume_text,
            missing_skills=missing_skills,
            target_role=target_role,
            custom_prompt=custom_prompt,
        )

    async def generate_resume_mcq_assessment_async(
        self,
        *,
        resume_text: str,
        jd_text: str = "",
        count: int = 10,
    ) -> dict:
        return await self.generate_resume_mcq_assessment(
            resume_text=resume_text,
            jd_text=jd_text,
            count=count,
        )

