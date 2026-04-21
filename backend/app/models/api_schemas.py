from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ORMBase(BaseModel):
    model_config = {"from_attributes": True}


class UserCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=6)
    new_password: str = Field(min_length=6)


class MessageOut(BaseModel):
    message: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    name: str
    email: str


class UserOut(ORMBase):
    id: UUID
    name: str
    email: str
    created_at: datetime


class DocumentJDOverviewOut(BaseModel):
    company_name: str = "the company"
    role_title: str = "this role"
    overview: str = ""
    required_skills: list[str] = Field(default_factory=list)
    key_requirements: list[str] = Field(default_factory=list)
    what_to_prepare: list[str] = Field(default_factory=list)


class DocumentOut(ORMBase):
    id: UUID
    title: str
    content_hash: str
    created_at: datetime
    jd_overview: DocumentJDOverviewOut | None = None

class PracticeStartRequest(BaseModel):
    document_id: UUID
    analysis_record_id: str | None = Field(default=None, max_length=120)
    resume_text: str | None = Field(default=None, max_length=12000)
    input_type: str | None = Field(default=None, pattern="^(jd|resume)$")


class PracticeSessionOut(BaseModel):
    session_id: UUID
    document_id: UUID
    difficulty: int = Field(ge=1, le=3)


class QuestionOut(BaseModel):
    question_id: UUID
    question_text: str
    difficulty: int = Field(ge=1, le=3)


class AnswerSubmitRequest(BaseModel):
    session_id: UUID
    question_id: UUID
    answer: str = Field(min_length=1)


class AnswerSubmitOut(BaseModel):
    is_correct: bool
    feedback: str
    updated_difficulty: int = Field(ge=1, le=3)
    reference_answer: str | None = None


class HealthOut(BaseModel):
    status: str


class AnalysisMatchOut(BaseModel):
    analysis_record_id: str = ""
    jd_filename: str
    resume_filename: str
    company_name: str = ""
    role_title: str = ""
    overall_score: int = Field(ge=0, le=100)
    verdict: str
    matched_keywords: list[str]
    missing_keywords: list[str]
    resume_role_keywords: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    critical_missing_skills: list[str] = Field(default_factory=list)
    low_match_reasons: list[str] = Field(default_factory=list)
    suggested_roles: list[str] = Field(default_factory=list)
    role_fit_advice: str = ""
    practice_score: int = Field(default=0, ge=0, le=100)
    practice_feedback: list[str] = Field(default_factory=list)
    jd_key_points: list[str]
    resume_highlights: list[str]
    recommendations: list[str]
    summary: str
    uses_llm: bool = False
    uses_rag: bool = False


class HRPracticeStartRequest(BaseModel):
    analysis_record_id: str


class HRPracticeQuestionOut(BaseModel):
    question_id: str
    question: str
    focus: str = ""


class HRPracticeStartOut(BaseModel):
    analysis_record_id: str
    role_track: str
    questions: list[HRPracticeQuestionOut]


class HRPracticeAnswerIn(BaseModel):
    question_id: str
    question: str
    answer: str = Field(min_length=1, max_length=1500)


class HRPracticeEvaluateRequest(BaseModel):
    analysis_record_id: str
    answers: list[HRPracticeAnswerIn]


class HRPracticeAnswerFeedbackOut(BaseModel):
    question_id: str
    question: str
    submitted_answer: str
    score: int = Field(ge=0, le=100)
    feedback: str
    improved_answer: str


class HRPracticeEvaluateOut(BaseModel):
    analysis_record_id: str
    role_track: str
    overall_score: int = Field(ge=0, le=100)
    verdict: str
    answer_feedback: list[HRPracticeAnswerFeedbackOut]
    final_tips: list[str]
    uses_llm: bool = False


class SkillUpdateStartRequest(BaseModel):
    analysis_record_id: str


class SkillUpdateItemOut(BaseModel):
    skill: str
    why_missing: str
    how_to_fix: list[str] = Field(default_factory=list)


class SkillUpdateStartOut(BaseModel):
    analysis_record_id: str
    role_track: str
    missing_skills: list[str] = Field(default_factory=list)
    skill_details: list[SkillUpdateItemOut] = Field(default_factory=list)


class SkillRoadmapRequest(BaseModel):
    analysis_record_id: str | None = None
    target: str = Field(min_length=1, max_length=120)


class SkillRoadmapStepOut(BaseModel):
    level: str
    action_items: list[str] = Field(default_factory=list)


class SkillRoadmapPhaseOut(BaseModel):
    phase: str
    focus: str
    subtopics: list[str] = Field(default_factory=list)
    practice: list[str] = Field(default_factory=list)


class SkillRoadmapOut(BaseModel):
    analysis_record_id: str | None = None
    target: str
    overview: str
    roadmap_steps: list[SkillRoadmapStepOut] = Field(default_factory=list)
    detailed_plan: list[SkillRoadmapPhaseOut] = Field(default_factory=list)
    flowchart_text: str = ""
    projects: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    generated_by: str = "fallback"


class SkillStepAssessmentStartRequest(BaseModel):
    analysis_record_id: str | None = None
    target: str = Field(min_length=1, max_length=120)
    step_title: str = Field(min_length=1, max_length=140)
    step_description: str = Field(default="", max_length=600)
    action_items: list[str] = Field(default_factory=list, max_length=80)
    question_count: int = Field(default=10, ge=5, le=20)


class SkillStepAssessmentStartOut(BaseModel):
    session_id: str
    analysis_record_id: str | None = None
    target: str
    step_title: str
    learning_content: str
    key_points: list[str] = Field(default_factory=list)
    pass_threshold: int = Field(default=60, ge=1, le=100)
    total_questions: int = Field(ge=1)
    questions: list[dict[str, Any]] = Field(default_factory=list)
    generated_by: str = "fallback"


class SkillStepAssessmentEvaluateRequest(BaseModel):
    session_id: str
    answers: list[dict[str, Any]] = Field(default_factory=list)


class SkillStepAssessmentEvaluateOut(BaseModel):
    session_id: str
    total_questions: int = Field(ge=1)
    correct_count: int = Field(ge=0)
    score_percentage: int = Field(ge=0, le=100)
    pass_threshold: int = Field(default=60, ge=1, le=100)
    passed: bool
    motivation: str
    results: list[dict[str, Any]] = Field(default_factory=list)


class ResumeUpgradeGenerateRequest(BaseModel):
    analysis_record_id: str
    custom_prompt: str | None = Field(default=None, max_length=1200)


class ResumeUpgradeOut(BaseModel):
    analysis_record_id: str
    target_role: str = ""
    ats_resume: str
    missing_skills_considered: list[str] = Field(default_factory=list)
    missing_skills_added: list[str] = Field(default_factory=list)
    improvement_notes: list[str] = Field(default_factory=list)
    uses_llm: bool = False


class MCQAssessmentStartRequest(BaseModel):
    analysis_record_id: str
    question_count: int = Field(default=10, ge=10, le=20)


class MCQAssessmentQuestionOut(BaseModel):
    question_id: str
    question: str
    options: list[str] = Field(min_length=4, max_length=4)


class MCQAssessmentStartOut(BaseModel):
    analysis_record_id: str
    role_track: str = "General Professional Role"
    total_questions: int = Field(ge=1)
    questions: list[MCQAssessmentQuestionOut]


class MCQAssessmentAnswerIn(BaseModel):
    question_id: str
    selected_option_index: int = Field(ge=0, le=3)


class MCQAssessmentEvaluateRequest(BaseModel):
    analysis_record_id: str
    answers: list[MCQAssessmentAnswerIn]


class MCQAssessmentResultOut(BaseModel):
    question_id: str
    question: str
    selected_option_index: int = Field(ge=0, le=3)
    selected_answer: str
    is_correct: bool
    correct_option_index: int = Field(ge=0, le=3)
    correct_answer: str


class MCQAssessmentEvaluateOut(BaseModel):
    analysis_record_id: str
    total_questions: int = Field(ge=1)
    correct_count: int = Field(ge=0)
    score_percentage: int = Field(ge=0, le=100)
    results: list[MCQAssessmentResultOut]


class ResumeAssessmentQuestionOut(BaseModel):
    question_id: str
    question: str
    focus: str = ""


class ResumeAssessmentStartOut(BaseModel):
    analysis_record_id: str
    role_track: str = "General Professional Role"
    total_questions: int = Field(ge=1)
    questions: list[ResumeAssessmentQuestionOut]


class ResumeAssessmentAnswerIn(BaseModel):
    question_id: str
    question: str
    answer: str = Field(min_length=1, max_length=1500)


class ResumeAssessmentEvaluateRequest(BaseModel):
    analysis_record_id: str
    answers: list[ResumeAssessmentAnswerIn]


class ResumeAssessmentAnswerFeedbackOut(BaseModel):
    question_id: str
    question: str
    submitted_answer: str
    score: int = Field(ge=0, le=100)
    feedback: str
    improved_answer: str
    is_correct: bool = False


class ResumeAssessmentEvaluateOut(BaseModel):
    analysis_record_id: str
    role_track: str
    overall_score: int = Field(ge=0, le=100)
    verdict: str
    answer_feedback: list[ResumeAssessmentAnswerFeedbackOut]
    final_tips: list[str]
    uses_llm: bool = False
