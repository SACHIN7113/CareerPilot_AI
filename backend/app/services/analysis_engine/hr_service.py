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
class AnalysisHrMixin:
    async def generate_hr_questions(self, *, jd_text: str, resume_text: str, count: int = 6) -> dict:
        _ = jd_text
        _ = resume_text
        requested_count = max(1, min(8, int(count or 6)))
        role_track = "HR Interview Round"
        return {
            "role_track": role_track,
            "questions": self._fixed_hr_questions(count=requested_count),
        }

    def _fixed_hr_questions(self, *, count: int) -> list[dict[str, str]]:
        question_bank = [
            {"question": "Tell me about yourself.", "focus": "Introduction"},
            {"question": "Why do you want this role?", "focus": "Motivation"},
            {"question": "What do you know about our company?", "focus": "Company research"},
            {
                "question": "Why should we hire you, and what are your strengths and weaknesses?",
                "focus": "Self-awareness",
            },
            {"question": "How do you handle pressure or deadlines?", "focus": "Work style"},
            {"question": "Where do you see yourself in the next 3 to 5 years?", "focus": "Career goals"},
            {
                "question": "Are you comfortable with shift, relocation, or bond requirements?",
                "focus": "Availability",
            },
            {"question": "Do you have any questions for us?", "focus": "Candidate curiosity"},
        ]
        return question_bank[: max(1, min(8, count))]

    async def evaluate_hr_answers(
        self,
        *,
        jd_text: str,
        resume_text: str,
        answers: list[dict[str, str]],
    ) -> dict:
        jd_clean = self._normalize(jd_text)
        resume_clean = self._normalize(resume_text)
        role_track = "HR Interview Round"
        jd_terms = self._extract_ranked_terms(jd_clean, limit=24)
        required_skills = self._extract_required_skills(jd_clean, jd_terms)

        normalized_answers: list[dict[str, str]] = []
        for item in answers[:8]:
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
            raise RuntimeError("No HR practice answers provided for evaluation.")

        llm_result: dict = {}
        if settings.analysis_llm_refinement and self.model is not None:
            llm_result = self._llm_evaluate_hr_answers(
                role_track=role_track,
                required_skills=required_skills,
                jd_text=jd_clean,
                resume_text=resume_clean,
                answers=normalized_answers,
            )

        feedback_items = llm_result.get("answer_feedback") if isinstance(llm_result, dict) else []
        uses_llm = bool(feedback_items)
        if not feedback_items:
            feedback_items = self._fallback_evaluate_hr_answers(
                answers=normalized_answers,
                role_track=role_track,
                required_skills=required_skills,
                jd_terms=jd_terms,
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
            has_placeholder = bool(re.search(r"\[[^\]]+\]", raw_improved_answer or ""))

            if not question_id or not question or not submitted_answer:
                continue

            if not improved_answer or has_placeholder:
                improved_answer = self._compose_improved_answer(
                    question=question,
                    answer=submitted_answer,
                    role_track=role_track,
                    required_skills=required_skills,
                    resume_text=resume_clean,
                )
            improved_answer = self._ensure_resume_grounding(
                improved_answer=improved_answer,
                resume_text=resume_clean,
                required_skills=required_skills,
            )
            if not feedback:
                feedback = "Answer is relevant; add a concrete project outcome to strengthen interview impact."

            sanitized_feedback.append(
                {
                    "question_id": question_id,
                    "question": question,
                    "submitted_answer": submitted_answer,
                    "score": score,
                    "feedback": feedback,
                    "improved_answer": improved_answer,
                }
            )
            scores.append(score)

        if not sanitized_feedback:
            sanitized_feedback = self._fallback_evaluate_hr_answers(
                answers=normalized_answers,
                role_track=role_track,
                required_skills=required_skills,
                jd_terms=jd_terms,
                resume_text=resume_clean,
            )
            scores = [int(item.get("score") or 0) for item in sanitized_feedback]
            uses_llm = False

        overall_score = int(round(sum(scores) / max(1, len(scores))))
        verdict = "Strong" if overall_score >= 75 else "Moderate" if overall_score >= 55 else "Needs Improvement"
        final_tips = self._clean_string_list((llm_result or {}).get("final_tips"), max_items=5)
        if not final_tips:
            final_tips = self._build_hr_final_tips(
                overall_score=overall_score,
                role_track=role_track,
                required_skills=required_skills,
            )

        return {
            "role_track": role_track,
            "overall_score": max(0, min(100, overall_score)),
            "verdict": verdict,
            "answer_feedback": sanitized_feedback,
            "final_tips": final_tips,
            "uses_llm": uses_llm,
        }

    def _detect_role_track(self, jd_text: str, resume_text: str) -> str:
        jd_only = self._normalize(jd_text)
        resume_only = self._normalize(resume_text)
        lowered_jd = (jd_text or "").lower()

        # Hard-priority role cues from JD should override resume bias.
        explicit_jd_priority = [
            ("QA Engineer", r"\b(?:qa|quality\s+assurance|software\s+test(?:er|ing)|manual\s+testing|automation\s+testing|test\s+case)\b"),
            ("Sales Executive", r"\b(?:sales|business\s+development|account\s+executive|lead\s+generation|revenue|pipeline)\b"),
            ("DevOps Engineer", r"\b(?:devops|sre|infrastructure|ci\s*/?\s*cd|kubernetes|terraform)\b"),
            ("Frontend Developer", r"\b(?:frontend|front[-\s]?end|ui\s+developer|react\s+developer)\b"),
            ("Backend Developer", r"\b(?:backend|back[-\s]?end|api\s+developer|microservices?)\b"),
            ("Data Analyst", r"\b(?:data\s+analyst|analytics|business\s+intelligence|reporting)\b"),
            ("Technical Support Engineer", r"\b(?:technical\s+support|support\s+engineer|incident\s+management|customer\s+support)\b"),
        ]
        for role, pattern in explicit_jd_priority:
            if re.search(pattern, lowered_jd, flags=re.IGNORECASE):
                return role

        role_hints = {
            "Backend Developer": ("backend", "api", "microservice"),
            "QA Engineer": ("qa", "quality assurance", "testing"),
            "DevOps Engineer": ("devops", "infra", "deployment", "sre"),
            "Frontend Developer": ("frontend", "ui", "react", "javascript"),
            "Data Analyst": ("data analyst", "analytics", "bi", "reporting"),
            "Technical Support Engineer": ("support", "customer", "incident", "troubleshooting"),
            "Sales Executive": ("sales", "business development", "revenue", "pipeline", "lead"),
        }

        best_role = "General Professional Role"
        best_score = 0
        for role, skills in self._ROLE_SKILL_MAP.items():
            score = 0
            for skill in skills:
                if self._contains_term_in_text(skill, jd_only):
                    score += 4
                if self._contains_term_in_text(skill, resume_only):
                    score += 1

            for hint in role_hints.get(role, ()):
                if hint in lowered_jd:
                    score += 5

            if score > best_score:
                best_score = score
                best_role = role

        return best_role

    def _llm_generate_hr_questions(
        self,
        *,
        role_track: str,
        required_skills: list[str],
        jd_text: str,
        resume_text: str,
        count: int,
    ) -> list[dict[str, str]]:
        model_candidates = []
        if self.model is not None:
            model_candidates.append(self.model)
        for model_name in self._candidate_model_names():
            model = get_model(model_name)
            if model is not None:
                model_candidates.append(model)

        if not model_candidates:
            return []

        prompt = (
            "Generate interview HR/practical questions tailored to the candidate and role. "
            "Questions must be role-specific, realistic, and not generic. "
            "Return a balanced mix: exactly half technical questions and half HR/behavioral questions. "
            "Each focus must start with either 'Technical' or 'HR'. "
            "Return STRICT JSON only: {\"questions\":[{\"question\":\"...\",\"focus\":\"Technical - ... or HR - ...\"}]}. "
            f"Return exactly {count} questions."
        )
        context = (
            f"Role track: {role_track}\n"
            f"Required skills: {', '.join(required_skills[:8]) or 'none'}\n\n"
            f"Job Description:\n{jd_text[:7000]}\n\n"
            f"Resume:\n{resume_text[:5000]}"
        )

        for model in model_candidates:
            try:
                response = model.generate_content(
                    f"{prompt}\n\n{context}",
                    generation_config={"temperature": 0.2, "response_mime_type": "application/json"},
                )
                raw = extract_text(response) or "{}"
                parsed = parse_json_response(raw)
                self.model = model

                questions = parsed.get("questions") if isinstance(parsed, dict) else None
                if not isinstance(questions, list):
                    continue

                normalized: list[dict[str, str]] = []
                for item in questions:
                    if not isinstance(item, dict):
                        continue
                    question = self._clean_text(item.get("question"), max_len=220)
                    focus = self._clean_text(item.get("focus"), max_len=80)
                    if not question:
                        continue
                    normalized.append({"question": question, "focus": focus or "General fit"})
                    if len(normalized) >= count:
                        break

                if normalized:
                    return normalized
            except Exception:
                continue

        return []

    def _fallback_hr_questions(self, role_track: str, required_skills: list[str], *, count: int) -> list[dict[str, str]]:
        filtered_skills = [
            skill
            for skill in self._clean_skill_output(required_skills, max_items=12)
            if self._skill_key(skill) not in self._MOTIVATION_TOKENS
        ]
        top_skill_1 = filtered_skills[0] if filtered_skills else "role skills"
        top_skill_2 = filtered_skills[1] if len(filtered_skills) > 1 else top_skill_1
        top_skill_3 = filtered_skills[2] if len(filtered_skills) > 2 else top_skill_2

        role_specific: dict[str, list[dict[str, str]]] = {
            "Backend Developer": [
                {"question": f"Describe a backend project where you used {top_skill_1} to solve a real production problem", "focus": "Technical - project depth"},
                {"question": f"How do you design reliable APIs and handle trade-offs related to {top_skill_2}", "focus": "Technical - system thinking"},
                {"question": "How do you ensure code quality and testing discipline in fast delivery environments", "focus": "Technical - quality mindset"},
                {"question": f"Why do you want this {role_track} role and how does it align with your long-term goals", "focus": "HR - role motivation"},
                {"question": f"If hired, how would you contribute in the first 90 days using {top_skill_3}", "focus": "HR - impact plan"},
                {"question": "Where do you see yourself in 3 to 5 years in engineering", "focus": "HR - career direction"},
            ],
            "QA Engineer": [
                {"question": f"Explain how you design an effective test strategy for features requiring {top_skill_1}", "focus": "Technical - test strategy"},
                {"question": "Tell us about a defect you caught early, how you reproduced it, and what impact it prevented", "focus": "Technical - defect analysis"},
                {"question": f"How do you balance manual testing and automation testing when deadlines are tight around {top_skill_2}", "focus": "Technical - execution trade-offs"},
                {"question": "Why are you interested in this QA role", "focus": "HR - role motivation"},
                {"question": "How would you collaborate with developers and product managers during release crunch", "focus": "HR - collaboration"},
                {"question": "Where do you see your QA career in 3 to 5 years", "focus": "HR - career direction"},
            ],
            "DevOps Engineer": [
                {"question": f"Describe a deployment pipeline you improved with {top_skill_1}", "focus": "Technical - delivery pipeline"},
                {"question": f"How do you approach reliability and incident prevention using {top_skill_2}", "focus": "Technical - reliability"},
                {"question": "How do you balance speed, security, and cost in infrastructure decisions", "focus": "Technical - architecture trade-offs"},
                {"question": "Why do you want to work in this DevOps-focused role", "focus": "HR - role motivation"},
                {"question": "What would be your first 90-day plan in this team", "focus": "HR - impact plan"},
                {"question": "Where do you see yourself in 3 to 5 years in platform engineering", "focus": "HR - career direction"},
            ],
            "Sales Executive": [
                {"question": "Describe how you build and manage a qualified sales pipeline", "focus": "Technical - sales execution"},
                {"question": "How do you handle objections and move a hesitant prospect toward closure", "focus": "Technical - negotiation"},
                {"question": "Which CRM metrics do you track weekly and how do you improve them", "focus": "Technical - metrics"},
                {"question": "Why are you interested in this sales role", "focus": "HR - role motivation"},
                {"question": "How do you collaborate with marketing and product teams to improve conversions", "focus": "HR - collaboration"},
                {"question": "Where do you see your sales career in 3 to 5 years", "focus": "HR - career direction"},
            ],
        }

        generic = [
            {"question": f"Describe a project where you demonstrated {top_skill_1}", "focus": "Technical - project depth"},
            {"question": f"How do you solve difficult work problems related to {top_skill_2}", "focus": "Technical - problem solving"},
            {"question": f"What technical strengths make you suitable for a {role_track} role", "focus": "Technical - strengths"},
            {"question": f"Why do you want this {role_track} role", "focus": "HR - role motivation"},
            {"question": "What value will you bring in your first 90 days", "focus": "HR - impact plan"},
            {"question": "Where do you see yourself in 3 to 5 years", "focus": "HR - career direction"},
        ]

        selected = role_specific.get(role_track, generic)
        return selected[:count]

    def _is_technical_question(self, question: str, focus: str) -> bool:
        text = f"{focus} {question}".lower()
        technical_tokens = (
            "technical",
            "project",
            "test",
            "testing",
            "automation",
            "api",
            "architecture",
            "pipeline",
            "metrics",
            "debug",
            "strategy",
            "reliability",
            "design",
            "implementation",
            "defect",
            "crm",
            "sales execution",
        )
        return any(token in text for token in technical_tokens)

    def _is_hr_question(self, question: str, focus: str) -> bool:
        text = f"{focus} {question}".lower()
        hr_tokens = (
            "hr",
            "role motivation",
            "career",
            "where do you see",
            "why do you want",
            "collaboration",
            "impact plan",
            "team",
            "company",
            "behavioral",
            "communication",
        )
        return any(token in text for token in hr_tokens)

    def _enforce_hr_technical_mix(
        self,
        *,
        questions: list[dict[str, str]],
        role_track: str,
        required_skills: list[str],
        count: int,
    ) -> list[dict[str, str]]:
        target_hr = max(2, count // 2)
        target_technical = max(2, count - target_hr)

        technical = [item for item in questions if self._is_technical_question(item.get("question", ""), item.get("focus", ""))]
        hr = [item for item in questions if self._is_hr_question(item.get("question", ""), item.get("focus", ""))]
        other = [
            item
            for item in questions
            if item not in technical and item not in hr
        ]

        fallback = self._fallback_hr_questions(role_track, required_skills, count=max(count, 6))
        fallback_technical = [item for item in fallback if self._is_technical_question(item.get("question", ""), item.get("focus", ""))]
        fallback_hr = [item for item in fallback if self._is_hr_question(item.get("question", ""), item.get("focus", ""))]

        seen: set[str] = set()
        mixed: list[dict[str, str]] = []

        def _tech_count() -> int:
            return sum(1 for item in mixed if self._is_technical_question(item["question"], item.get("focus", "")))

        def _hr_count() -> int:
            return sum(1 for item in mixed if self._is_hr_question(item["question"], item.get("focus", "")))

        def _append_unique(pool: list[dict[str, str]], *, category: str | None = None) -> None:
            for item in pool:
                if len(mixed) >= count:
                    break

                question = self._clean_text(item.get("question"), max_len=220)
                focus = self._clean_text(item.get("focus"), max_len=80)
                key = self._normalize_term(question)
                if not question or not key or key in seen:
                    continue

                if category == "technical" and not self._is_technical_question(question, focus):
                    continue
                if category == "hr" and not self._is_hr_question(question, focus):
                    continue

                seen.add(key)
                mixed.append({"question": question, "focus": focus or "General fit"})

                if category == "technical" and _tech_count() >= target_technical:
                    break
                if category == "hr" and _hr_count() >= target_hr:
                    break

        _append_unique(technical, category="technical")
        if _tech_count() < target_technical:
            _append_unique(fallback_technical, category="technical")

        _append_unique(hr, category="hr")
        if _hr_count() < target_hr:
            _append_unique(fallback_hr, category="hr")

        _append_unique(other + fallback)

        return mixed[:count]

    def _llm_evaluate_hr_answers(
        self,
        *,
        role_track: str,
        required_skills: list[str],
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
            "Evaluate interview answers as a hiring panel. Be practical and coaching-oriented. "
            "Return STRICT JSON only with keys: overall_score (0-100), answer_feedback (array), final_tips (array). "
            "Each answer_feedback item must include: question_id, question, submitted_answer, score (0-100), feedback, improved_answer. "
            "Improved answer should be concise, professional, directly usable in interview, and specific to what the question asks. "
            "Ground improved answers in available resume evidence (skills/projects/background) when relevant."
        )
        context = (
            f"Role track: {role_track}\n"
            f"Required skills: {', '.join(required_skills[:8]) or 'none'}\n\n"
            f"Job Description:\n{jd_text[:2200]}\n\n"
            f"Resume:\n{resume_text[:1600]}\n\n"
            f"Candidate Answers:\n{answers_context[:6000]}"
        )

        max_attempts = 1 if settings.analysis_fast_mode else min(2, len(model_candidates))
        if settings.analysis_llm_refinement:
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

    def _fallback_evaluate_hr_answers(
        self,
        *,
        answers: list[dict[str, str]],
        role_track: str,
        required_skills: list[str],
        jd_terms: list[str],
        resume_text: str = "",
    ) -> list[dict]:
        fallback_items: list[dict] = []
        reference_terms = self._clean_skill_output(required_skills + jd_terms[:10], max_items=10)

        for item in answers:
            answer = item["answer"]
            word_count = len(answer.split())
            alignment_hits = sum(1 for term in reference_terms if self._contains_term_in_text(term, answer))

            score = 35 + min(30, int(word_count * 1.1)) + min(25, alignment_hits * 8)
            score = max(0, min(100, score))

            if score >= 80:
                feedback = "Strong answer with clear relevance. Add one quantified impact to make it interview-ready."
            elif score >= 60:
                feedback = "Good base answer; make it more specific with scenario, action, and measurable result."
            else:
                feedback = "Answer is too generic. Tie it to concrete role responsibilities and real project outcomes."

            improved = self._compose_improved_answer(
                question=item["question"],
                answer=answer,
                role_track=role_track,
                required_skills=required_skills,
                resume_text=resume_text,
            )
            improved = self._ensure_resume_grounding(
                improved_answer=improved,
                resume_text=resume_text,
                required_skills=required_skills,
            )

            fallback_items.append(
                {
                    "question_id": item["question_id"],
                    "question": item["question"],
                    "submitted_answer": answer,
                    "score": score,
                    "feedback": feedback,
                    "improved_answer": improved,
                }
            )

        return fallback_items

    def _compose_improved_answer(
        self,
        *,
        question: str,
        answer: str,
        role_track: str,
        required_skills: list[str],
        resume_text: str = "",
    ) -> str:
        question_text = self._clean_text(question, max_len=220)
        answer_text = self._clean_text(answer, max_len=1200)
        intent = self._detect_hr_question_intent(question_text)
        role_label = self._display_role_label(role_track)

        mentioned_skills = self._extract_answer_skills(
            answer_text,
            resume_text,
            required_skills,
            max_items=3,
        )
        focus = ", ".join(mentioned_skills) if mentioned_skills else "relevant technical and collaboration skills"
        lead = self._extract_answer_lead(answer_text)

        if intent == "intro":
            name = self._extract_candidate_name(answer_text)
            profile = self._extract_profile_phrase(answer_text, role_label)
            profile = re.sub(r"^(?:i\s+am|i'm)\s+", "", profile, flags=re.IGNORECASE)
            intro_open = f"My name is {name}, and I am " if name else "I am "
            improved = (
                f"{intro_open}{profile}. "
                f"I have built hands-on experience in {focus}. "
                "I am now looking to contribute these strengths in a role where I can learn fast and deliver measurable results."
            )
        elif intent == "role_motivation":
            improved = (
                f"I want this opportunity because it aligns with my interests and strengths in {focus}. "
                f"From my recent work, {lead}. "
                "This role will help me grow while contributing quickly to meaningful product outcomes."
            )
        elif intent == "company_knowledge":
            improved = (
                "From my research, your company focuses on building quality solutions with real business impact. "
                f"That aligns with my preference for practical, outcome-driven work and my background in {focus}. "
                "If selected, I can contribute with ownership, collaboration, and continuous improvement."
            )
        elif intent == "strengths_weaknesses":
            weakness = self._extract_weakness_phrase(answer_text)
            improved = (
                f"You should hire me because I bring strong ownership, learning agility, and practical skills in {focus}. "
                f"One of my strengths is {self._extract_strength_phrase(answer_text)}. "
                f"A weakness I actively manage is {weakness}, and I improve it through structured planning and regular feedback."
            )
        elif intent == "pressure_deadlines":
            improved = (
                "I handle pressure by breaking work into priorities, focusing on high-impact tasks first, and tracking progress with clear checkpoints. "
                f"In practice, {lead}. "
                "This approach helps me meet deadlines without compromising quality."
            )
        elif intent == "career_goals":
            improved = (
                "In the next 3 to 5 years, I want to grow into a dependable professional who can own end-to-end delivery. "
                f"In the near term, I plan to deepen my expertise in {focus}. "
                "Long term, I aim to contribute to architecture decisions and mentor others in the team."
            )
        elif intent == "availability":
            stance = self._build_availability_stance(answer_text)
            improved = (
                f"{stance} "
                "I am flexible with business needs and can adapt responsibly while maintaining consistent performance and communication."
            )
        elif intent == "candidate_questions":
            improved = (
                "Yes, I would like to ask a few questions: what are the top priorities for this role in the first 90 days, "
                "how success is measured, and what learning or growth opportunities are available within the team."
            )
        else:
            improved = (
                f"I am interested in this opportunity because it aligns with my strengths in {focus}. "
                f"From my recent work, {lead}. "
                "I would contribute through clear ownership, collaboration, and measurable business impact."
            )

        return self._clean_text(improved, max_len=650)

    def _detect_hr_question_intent(self, question: str) -> str:
        text = self._normalize_term(question)
        if any(token in text for token in ("tell me about yourself", "introduce yourself", "about yourself")):
            return "intro"
        if any(token in text for token in ("why do you want this role", "why this role", "why do you want this job")):
            return "role_motivation"
        if "what do you know about our company" in text or ("company" in text and "know" in text):
            return "company_knowledge"
        if "why should we hire" in text or "strength" in text or "weakness" in text:
            return "strengths_weaknesses"
        if "pressure" in text or "deadline" in text or "stress" in text:
            return "pressure_deadlines"
        if "where do you see yourself" in text or "3 to 5 years" in text or "next 3" in text:
            return "career_goals"
        if "shift" in text or "relocation" in text or "bond" in text:
            return "availability"
        if "any questions" in text and "for us" in text:
            return "candidate_questions"
        return "generic"

    def _display_role_label(self, role_track: str) -> str:
        text = self._clean_text(role_track, max_len=60)
        if not text or text in {"General Professional Role", "HR Interview Round"}:
            return "role"
        return text

    def _extract_candidate_name(self, answer: str) -> str:
        match = re.search(
            r"\bmy name is\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,3})\b",
            answer or "",
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        raw = re.sub(r"\s+", " ", match.group(1)).strip(" .,")

        stop_tokens = {"so", "currently", "and", "i", "am", "working", "pursuing"}
        words: list[str] = []
        for token in raw.split(" "):
            if token.lower() in stop_tokens:
                break
            words.append(token)

        if not words:
            return ""

        cleaned_name = " ".join(words[:3])
        return self._clean_text(cleaned_name, max_len=40)

    def _extract_answer_lead(self, answer: str) -> str:
        first = re.split(r"(?<=[.!?])\s+", answer or "", maxsplit=1)[0]
        cleaned = self._clean_text(first, max_len=170).rstrip(" .,!?:;")
        if cleaned:
            return cleaned
        return "I have delivered relevant outcomes in project-based work"

    def _extract_profile_phrase(self, answer: str, role_label: str) -> str:
        text = self._normalize(answer or "")
        patterns = (
            r"\b(?:i am|i'm)\s+([^\.]{6,80})",
            r"\b(?:recent|final year)\s+([^\.]{6,80})",
            r"\b([0-9]+\+?\s+years?\s+of\s+experience[^\.]{0,50})",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                candidate = self._clean_text(match.group(1), max_len=90).strip(" ,.")
                if candidate:
                    return candidate
        if role_label == "role":
            return "a motivated candidate preparing for this opportunity"
        return f"a motivated candidate preparing for a {role_label} position"

    def _extract_answer_skills(
        self,
        answer: str,
        resume_text: str,
        required_skills: list[str],
        *,
        max_items: int,
    ) -> list[str]:
        mentioned = [skill for skill in required_skills if self._contains_term_in_text(skill, answer)]
        if mentioned:
            return self._clean_skill_output(mentioned, max_items=max_items)

        resume_mentions = [skill for skill in required_skills if self._contains_term_in_text(skill, resume_text)]
        if resume_mentions:
            return self._clean_skill_output(resume_mentions, max_items=max_items)

        tokens = self._extract_ranked_terms(answer, limit=14)
        inferred = [token for token in tokens if token in self._TECH_HINT_TOKENS or token in self._SKILL_PHRASES]
        if inferred:
            return self._clean_skill_output(inferred, max_items=max_items)

        resume_tokens = self._extract_ranked_terms(resume_text or "", limit=20)
        resume_inferred = [token for token in resume_tokens if token in self._TECH_HINT_TOKENS or token in self._SKILL_PHRASES]
        return self._clean_skill_output(resume_inferred or required_skills[:max_items], max_items=max_items)

    def _extract_resume_skill_signals(self, resume_text: str, required_skills: list[str], *, max_items: int) -> list[str]:
        if not resume_text:
            return []

        matched_required = [skill for skill in required_skills if self._contains_term_in_text(skill, resume_text)]
        if matched_required:
            return self._clean_skill_output(matched_required, max_items=max_items)

        resume_tokens = self._extract_ranked_terms(resume_text, limit=24)
        inferred = [token for token in resume_tokens if token in self._TECH_HINT_TOKENS or token in self._SKILL_PHRASES]
        return self._clean_skill_output(inferred, max_items=max_items)

    def _ensure_resume_grounding(self, *, improved_answer: str, resume_text: str, required_skills: list[str]) -> str:
        base = self._clean_text(improved_answer, max_len=650)
        if not base or not resume_text:
            return base

        resume_signals = self._extract_resume_skill_signals(resume_text, required_skills, max_items=3)
        if not resume_signals:
            return base

        if any(self._contains_term_in_text(skill, base) for skill in resume_signals):
            return base

        grounding = f"Based on your resume, you have relevant experience in {', '.join(resume_signals)}."
        return self._clean_text(f"{base} {grounding}", max_len=650)

    def _sanitize_improved_answer_text(self, value: str) -> str:
        text = self._clean_text(value, max_len=650)
        text = re.sub(r"\[[^\]]+\]", "", text)
        text = re.sub(r"\s+", " ", text).strip(" ,;:-")
        return text

    def _extract_strength_phrase(self, answer: str) -> str:
        text = self._normalize(answer or "")
        match = re.search(r"\bstrength(?:s)?\s+(?:is|are)?\s*([^\.]{6,80})", text, flags=re.IGNORECASE)
        if match:
            phrase = self._clean_text(match.group(1), max_len=90).strip(" ,.")
            if phrase:
                return phrase
        return "my ability to learn quickly and execute consistently under guidance"

    def _extract_weakness_phrase(self, answer: str) -> str:
        text = self._normalize(answer or "")
        match = re.search(r"\bweakness(?:es)?\s+(?:is|are)?\s*([^\.]{6,90})", text, flags=re.IGNORECASE)
        if match:
            phrase = self._clean_text(match.group(1), max_len=90).strip(" ,.")
            if phrase:
                return phrase

        if re.search(r"\b(?:overthink|perfection|nervous|hesitat|public speaking)\b", text, flags=re.IGNORECASE):
            return "occasionally over-focusing on details"

        return "spending extra time refining details beyond what is needed"

    def _build_availability_stance(self, answer: str) -> str:
        text = self._normalize_term(answer)
        if re.search(r"\b(not|cannot|can't|unable|no)\b", text) and re.search(r"\b(shift|relocation|bond)\b", text):
            return "I am open to discussing shift, relocation, or bond expectations based on role needs and practical constraints."
        return "I am comfortable with shift, relocation, or bond requirements when they are clearly communicated in advance."

    def _build_hr_final_tips(self, *, overall_score: int, role_track: str, required_skills: list[str]) -> list[str]:
        top_skills = ", ".join(required_skills[:3]) if required_skills else "core role skills"
        tips = [
            f"For {role_track} interviews, convert each answer into Situation-Action-Result format.",
            f"Use role-relevant terms naturally: {top_skills}.",
            "Add one measurable impact metric in every major answer.",
        ]
        if overall_score < 60:
            tips.append("Practice concise, role-specific answers before interviews to improve confidence and clarity.")
        else:
            tips.append("Your base answers are good. Focus on sharper storytelling and business impact.")
        return self._merge_unique(tips, max_items=5)

    def _as_score(self, value, fallback: int) -> int:
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return max(0, min(100, int(fallback)))

    def _normalize_verdict(self, value, score: int) -> str:
        text = self._clean_text(value, max_len=40)
        if text in {"Strong Match", "Moderate Match", "Low Match"}:
            return text
        return self._score_to_verdict(score)

    def _score_to_verdict(self, score: int) -> str:
        if score >= 75:
            return "Strong Match"
        if score >= 50:
            return "Moderate Match"
        return "Low Match"

    def _clean_string_list(self, value, *, max_items: int) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            text = self._clean_text(item, max_len=120)
            if text and text.lower() not in {entry.lower() for entry in cleaned}:
                cleaned.append(text)
            if len(cleaned) >= max_items:
                break
        return cleaned

    def _clean_text(self, value, *, max_len: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= max_len:
            return text

        # Prefer truncating on word boundaries so output reads naturally.
        window = text[: max_len + 1]
        last_space = window.rfind(" ")
        if last_space >= max(20, int(max_len * 0.6)):
            return window[:last_space].rstrip(" ,;:-")
        return text[:max_len].rstrip(" ,;:-")

    def _normalize(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        return cleaned[:20000]

    def _candidate_model_names(self) -> list[str]:
        preferred = [
            settings.gemini_model,
            "models/gemini-2.0-flash",
            "models/gemini-flash-lite-latest",
            "models/gemini-2.5-flash-lite",
            "models/gemini-2.5-flash",
        ]
        seen: set[str] = set()
        ordered: list[str] = []
        for item in preferred:
            if not item:
                continue
            if item not in seen:
                ordered.append(item)
                seen.add(item)
        return ordered


