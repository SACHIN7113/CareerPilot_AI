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
class AnalysisResumeMixin:
    async def evaluate_resume_answers(
        self,
        *,
        jd_text: str,
        resume_text: str,
        answers: list[dict[str, str]],
    ) -> dict:
        jd_clean = self._normalize(jd_text)
        resume_clean = self._normalize(resume_text)
        role_track = "Resume Skill Assessment"
        jd_terms = self._extract_ranked_terms(jd_clean, limit=24)
        required_skills = self._extract_required_skills(jd_clean, jd_terms)
        resume_skills = self._extract_resume_skill_signals(resume_clean, required_skills, max_items=18)

        normalized_answers: list[dict[str, str]] = []
        for item in answers[:20]:
            if not isinstance(item, dict):
                continue
            question_id = self._clean_text(item.get("question_id"), max_len=80)
            question = self._clean_text(item.get("question"), max_len=220)
            answer = self._clean_text(item.get("answer"), max_len=1500)
            if not answer:
                continue
            normalized_answers.append(
                {
                    "question_id": question_id or f"q{len(normalized_answers) + 1}",
                    "question": question or f"Question {len(normalized_answers) + 1}",
                    "answer": answer,
                }
            )

        if not normalized_answers:
            raise RuntimeError("No resume round answers provided for evaluation.")

        llm_result: dict = {}
        if settings.analysis_llm_refinement and self.model is not None:
            llm_result = self._llm_evaluate_resume_answers(
                role_track=role_track,
                resume_skills=resume_skills,
                jd_text=jd_clean,
                resume_text=resume_clean,
                answers=normalized_answers,
            )

        feedback_items = llm_result.get("answer_feedback") if isinstance(llm_result, dict) else []
        uses_llm = bool(feedback_items)
        if not feedback_items:
            feedback_items = self._fallback_evaluate_resume_answers(
                answers=normalized_answers,
                resume_skills=resume_skills,
                required_skills=required_skills,
                resume_text=resume_clean,
            )

        sanitized_feedback: list[dict] = []
        scores: list[int] = []
        for item in feedback_items:
            question_id = self._clean_text(item.get("question_id"), max_len=80)
            question = self._clean_text(item.get("question"), max_len=220)
            submitted_answer = self._clean_text(item.get("submitted_answer"), max_len=1500)
            score = self._as_score(item.get("score"), 0)
            feedback = self._clean_text(item.get("feedback"), max_len=320)
            raw_improved_answer = self._clean_text(item.get("improved_answer"), max_len=650)
            improved_answer = self._sanitize_improved_answer_text(raw_improved_answer)

            if not question_id or not question or not submitted_answer:
                continue

            if not improved_answer:
                improved_answer = self._compose_resume_improved_answer(
                    question=question,
                    answer=submitted_answer,
                    role_track=role_track,
                    resume_skills=resume_skills,
                    resume_text=resume_clean,
                )
            improved_answer = self._ensure_resume_grounding(
                improved_answer=improved_answer,
                resume_text=resume_clean,
                required_skills=resume_skills or required_skills,
            )

            if not feedback:
                feedback = "Answer is relevant; add concrete implementation detail and measurable impact."

            sanitized_feedback.append(
                {
                    "question_id": question_id,
                    "question": question,
                    "submitted_answer": submitted_answer,
                    "score": score,
                    "feedback": feedback,
                    "improved_answer": improved_answer,
                    "is_correct": score >= 70,
                }
            )
            scores.append(score)

        if not sanitized_feedback:
            sanitized_feedback = self._fallback_evaluate_resume_answers(
                answers=normalized_answers,
                resume_skills=resume_skills,
                required_skills=required_skills,
                resume_text=resume_clean,
            )
            scores = [int(item.get("score") or 0) for item in sanitized_feedback]
            uses_llm = False

        overall_score = int(round(sum(scores) / max(1, len(scores))))
        verdict = "Strong" if overall_score >= 75 else "Moderate" if overall_score >= 55 else "Needs Improvement"
        final_tips = self._clean_string_list((llm_result or {}).get("final_tips"), max_items=5)
        if not final_tips:
            final_tips = self._build_resume_final_tips(
                overall_score=overall_score,
                resume_skills=resume_skills,
            )

        return {
            "role_track": role_track,
            "overall_score": max(0, min(100, overall_score)),
            "verdict": verdict,
            "answer_feedback": sanitized_feedback,
            "final_tips": final_tips,
            "uses_llm": uses_llm,
        }

    def _llm_evaluate_resume_answers(
        self,
        *,
        role_track: str,
        resume_skills: list[str],
        jd_text: str,
        resume_text: str,
        answers: list[dict[str, str]],
    ) -> dict:
        model_candidates = []
        if self.model is not None:
            model_candidates.append(self.model)
        for model_name in self._candidate_model_names():
            model = get_model(model_name)
            if model is not None:
                model_candidates.append(model)

        if not model_candidates:
            return {}

        answers_context = "\n".join(
            f"{item['question_id']} | Q: {item['question']} | A: {item['answer']}" for item in answers
        )
        prompt = (
            "Evaluate resume-skill round answers for technical correctness and practical depth. "
            "Return STRICT JSON only with keys: overall_score (0-100), answer_feedback (array), final_tips (array). "
            "Each answer_feedback item must include: question_id, question, submitted_answer, score (0-100), feedback, improved_answer."
        )
        context = (
            f"Role track: {role_track}\n"
            f"Resume skills: {', '.join(resume_skills[:12]) or 'none'}\n\n"
            f"Job Description:\n{jd_text[:2200]}\n\n"
            f"Resume:\n{resume_text[:2200]}\n\n"
            f"Candidate Answers:\n{answers_context[:7000]}"
        )

        max_attempts = min(2, len(model_candidates))
        for model in model_candidates[:max_attempts]:
            try:
                response = model.generate_content(
                    f"{prompt}\n\n{context}",
                    generation_config={"temperature": 0.15, "response_mime_type": "application/json"},
                )
                raw = extract_text(response) or "{}"
                parsed = parse_json_response(raw)
                if isinstance(parsed, dict):
                    self.model = model
                    return parsed
            except Exception:
                continue

        return {}

    def _fallback_evaluate_resume_answers(
        self,
        *,
        answers: list[dict[str, str]],
        resume_skills: list[str],
        required_skills: list[str],
        resume_text: str,
    ) -> list[dict]:
        reference_terms = self._clean_skill_output(resume_skills or required_skills, max_items=12)
        fallback_items: list[dict] = []

        for item in answers:
            answer = item["answer"]
            word_count = len(answer.split())
            alignment_hits = sum(1 for term in reference_terms if self._contains_term_in_text(term, answer))

            score = 30 + min(30, int(word_count * 1.2)) + min(30, alignment_hits * 9)
            score = max(0, min(100, score))

            if score >= 80:
                feedback = "Strong technical response with good alignment. Add one precise metric or output value."
            elif score >= 60:
                feedback = "Relevant answer; improve with clearer implementation steps and measurable outcomes."
            else:
                feedback = "Answer is too generic or shallow. Connect directly to the asked skill with concrete implementation detail."

            improved = self._compose_resume_improved_answer(
                question=item["question"],
                answer=answer,
                role_track="Resume Skill Assessment",
                resume_skills=resume_skills or required_skills,
                resume_text=resume_text,
            )
            improved = self._ensure_resume_grounding(
                improved_answer=improved,
                resume_text=resume_text,
                required_skills=resume_skills or required_skills,
            )

            fallback_items.append(
                {
                    "question_id": item["question_id"],
                    "question": item["question"],
                    "submitted_answer": answer,
                    "score": score,
                    "feedback": feedback,
                    "improved_answer": improved,
                    "is_correct": score >= 70,
                }
            )

        return fallback_items

    def _compose_resume_improved_answer(
        self,
        *,
        question: str,
        answer: str,
        role_track: str,
        resume_skills: list[str],
        resume_text: str,
    ) -> str:
        _ = role_track
        _ = question
        lead = self._extract_answer_lead(answer)
        top_skills = self._extract_resume_skill_signals(resume_text, resume_skills, max_items=3)
        focus = ", ".join(top_skills or resume_skills[:3]) or "relevant technologies"

        improved = (
            f"In my project work, I applied {focus} to solve practical problems. "
            f"Specifically, {lead}. "
            "I validated the solution through testing and measurable outcomes such as reliability, performance, or delivery speed improvements."
        )
        return self._clean_text(improved, max_len=650)

    def _build_resume_final_tips(self, *, overall_score: int, resume_skills: list[str]) -> list[str]:
        top_skills = ", ".join(resume_skills[:3]) if resume_skills else "your strongest resume skills"
        tips = [
            f"Anchor each answer to one concrete resume skill such as: {top_skills}.",
            "Use a clear structure: problem, implementation steps, and measurable result.",
            "Mention tools, decisions, and trade-offs to show technical ownership.",
        ]
        if overall_score < 60:
            tips.append("Practice concise technical storytelling with one real project per key skill.")
        else:
            tips.append("Your base answers are good. Improve precision with metrics and production-like context.")
        return self._merge_unique(tips, max_items=5)


