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
class AnalysisAssessmentMixin:
    async def generate_mcq_assessment(self, *, jd_text: str, count: int = 10) -> dict:
        jd_clean = self._normalize(jd_text)
        requested_count = max(10, min(20, int(count or 10)))
        jd_terms = self._extract_ranked_terms(jd_clean, limit=30)
        required_skills = self._extract_required_skills(jd_clean, jd_terms)
        role_track = self._detect_role_track(jd_clean, "")

        llm_questions = self._llm_generate_mcq_questions(
            jd_text=jd_clean,
            required_skills=required_skills,
            role_track=role_track,
            count=requested_count,
        )

        normalized_questions: list[dict[str, object]] = []
        seen_questions: set[str] = set()

        for item in llm_questions:
            sanitized = self._sanitize_mcq_question_item(item)
            if not sanitized:
                continue
            options_key = "|".join(str(option) for option in sanitized.get("options", []))
            question_key = self._normalize_term(f"{sanitized['question']}|{options_key}")
            if question_key in seen_questions:
                continue
            seen_questions.add(question_key)
            normalized_questions.append(sanitized)
            if len(normalized_questions) >= requested_count:
                break

        if len(normalized_questions) < requested_count:
            fallback_questions = self._fallback_mcq_questions(
                jd_text=jd_clean,
                required_skills=required_skills,
                role_track=role_track,
                count=requested_count,
            )
            for item in fallback_questions:
                sanitized = self._sanitize_mcq_question_item(item)
                if not sanitized:
                    continue
                options_key = "|".join(str(option) for option in sanitized.get("options", []))
                question_key = self._normalize_term(f"{sanitized['question']}|{options_key}")
                if question_key in seen_questions:
                    continue
                seen_questions.add(question_key)
                normalized_questions.append(sanitized)
                if len(normalized_questions) >= requested_count:
                    break

        return {
            "role_track": role_track,
            "questions": normalized_questions[:requested_count],
        }

    async def generate_resume_mcq_assessment(self, *, resume_text: str, jd_text: str = "", count: int = 10) -> dict:
        resume_clean = self._normalize(resume_text)
        jd_clean = self._normalize(jd_text)
        requested_count = max(10, min(20, int(count or 10)))

        jd_terms = self._extract_ranked_terms(jd_clean, limit=24)
        required_skills = self._extract_required_skills(jd_clean, jd_terms)
        resume_skills = self._extract_resume_skill_signals(resume_clean, required_skills, max_items=18)
        if not resume_skills:
            resume_skills = self._clean_skill_output(self._extract_ranked_terms(resume_clean, limit=24), max_items=18)

        role_track = self._detect_role_track(jd_clean, resume_clean)

        llm_questions = self._llm_generate_resume_mcq_questions(
            resume_text=resume_clean,
            role_track=role_track,
            resume_skills=resume_skills,
            count=requested_count,
        )

        normalized_questions: list[dict[str, object]] = []
        seen_questions: set[str] = set()

        for item in llm_questions:
            sanitized = self._sanitize_mcq_question_item(item)
            if not sanitized:
                continue
            options_key = "|".join(str(option) for option in sanitized.get("options", []))
            question_key = self._normalize_term(f"{sanitized['question']}|{options_key}")
            if question_key in seen_questions:
                continue
            seen_questions.add(question_key)
            normalized_questions.append(sanitized)
            if len(normalized_questions) >= requested_count:
                break

        if len(normalized_questions) < requested_count:
            fallback_questions = self._fallback_resume_mcq_questions(
                resume_text=resume_clean,
                resume_skills=resume_skills,
                role_track=role_track,
                count=requested_count,
            )
            for item in fallback_questions:
                sanitized = self._sanitize_mcq_question_item(item)
                if not sanitized:
                    continue
                options_key = "|".join(str(option) for option in sanitized.get("options", []))
                question_key = self._normalize_term(f"{sanitized['question']}|{options_key}")
                if question_key in seen_questions:
                    continue
                seen_questions.add(question_key)
                normalized_questions.append(sanitized)
                if len(normalized_questions) >= requested_count:
                    break

            # If resume has limited unique skills, create safe question variations to satisfy 10/20 count.
            variation_index = 0
            while len(normalized_questions) < requested_count and fallback_questions:
                candidate = fallback_questions[variation_index % len(fallback_questions)]
                variation_index += 1
                sanitized = self._sanitize_mcq_question_item(candidate)
                if not sanitized:
                    continue

                base_question = str(sanitized["question"]).rstrip("?").strip()
                variant_no = len(normalized_questions) + 1
                sanitized["question"] = self._clean_text(f"{base_question} (Skill Check {variant_no})?", max_len=220)
                normalized_questions.append(sanitized)

        return {
            "role_track": role_track,
            "questions": normalized_questions[:requested_count],
        }

    def _llm_generate_resume_mcq_questions(
        self,
        *,
        resume_text: str,
        role_track: str,
        resume_skills: list[str],
        count: int,
    ) -> list[dict]:
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
            "Generate only RESUME SKILL ROUND MCQ questions from the candidate resume. "
            "Return STRICT JSON only in this format: "
            "{\"questions\":[{\"question\":\"...\",\"options\":[\"...\",\"...\",\"...\",\"...\"],\"correct_option_index\":0}]}. "
            f"Generate exactly {count} questions. "
            "Questions must be based on skills and technologies explicitly present in the resume. "
            "Do NOT generate HR or behavioral questions. Provide exactly 4 options and one correct option."
        )
        context = (
            f"Detected role track: {role_track}\n"
            f"Resume skills: {', '.join(resume_skills[:14]) or 'none'}\n\n"
            f"Resume:\n{resume_text[:9000]}"
        )

        max_attempts = min(2, len(model_candidates))
        for model in model_candidates[:max_attempts]:
            try:
                response = model.generate_content(
                    f"{prompt}\n\n{context}",
                    generation_config={"temperature": 0.2, "response_mime_type": "application/json"},
                )
                raw = extract_text(response) or "{}"
                parsed = parse_json_response(raw)
                questions = parsed.get("questions") if isinstance(parsed, dict) else None
                if not isinstance(questions, list):
                    continue

                self.model = model
                filtered: list[dict] = []
                for item in questions:
                    if not isinstance(item, dict):
                        continue
                    question = self._clean_text(item.get("question"), max_len=220)
                    if self._is_behavioral_question(question):
                        continue
                    filtered.append(item)

                return filtered
            except Exception:
                continue

        return []

    def _fallback_resume_mcq_questions(
        self,
        *,
        resume_text: str,
        resume_skills: list[str],
        role_track: str,
        count: int,
    ) -> list[dict[str, object]]:
        skills = self._clean_skill_output(resume_skills, max_items=18)
        if not skills:
            skills = self._clean_skill_output(self._extract_ranked_terms(resume_text, limit=20), max_items=18)
        if not skills:
            skills = ["communication", "problem solving", "team collaboration"]

        is_management = self._is_management_track(role_track, resume_text)
        if is_management:
            distractor_pool = [
                "Kernel-level debugging",
                "React hook optimization",
                "Compiler implementation",
                "Embedded firmware flashing",
                "GPU shading pipeline",
                "Low-level socket tuning",
                "JVM garbage collector internals",
                "Database kernel patches",
            ]
            question_templates = [
                "Based on the candidate resume, which management-side skill is clearly demonstrated?",
                "From the resume profile, which competency is relevant for planning or team coordination?",
                "Which of the following aligns with management or business execution experience in the resume?",
                "From the listed resume skills, which one best supports stakeholder or KPI-driven work?",
            ]
        else:
            distractor_pool = [
                "Warehouse dispatch planning",
                "Analog circuit soldering",
                "Fashion merchandising",
                "Tax return filing",
                "Legal arbitration drafting",
                "Hotel front-desk operations",
                "Bulk print production",
                "Offline event ticketing",
            ]
            question_templates = [
                "Based on the candidate resume, which technical skill is explicitly mentioned?",
                "From the resume technologies, which tool is relevant for this candidate profile?",
                "Which option best matches a technology listed in the resume skill set?",
                "According to the resume, which technical competency is demonstrated in projects or internships?",
            ]

        questions: list[dict[str, object]] = []
        for index in range(count):
            correct_skill = skills[index % len(skills)]
            wrong_1 = distractor_pool[index % len(distractor_pool)]
            wrong_2 = distractor_pool[(index + 2) % len(distractor_pool)]
            wrong_3 = skills[(index + 1) % len(skills)]
            if self._normalize_term(wrong_3) == self._normalize_term(correct_skill):
                wrong_3 = distractor_pool[(index + 4) % len(distractor_pool)]

            options = [wrong_1, wrong_2, wrong_3, correct_skill]
            correct_option_index = index % 4
            options[correct_option_index], options[3] = options[3], options[correct_option_index]

            questions.append(
                {
                    "question": question_templates[index % len(question_templates)],
                    "options": options,
                    "correct_option_index": correct_option_index,
                }
            )

        return questions

    def _llm_generate_mcq_questions(
        self,
        *,
        jd_text: str,
        required_skills: list[str],
        role_track: str,
        count: int,
    ) -> list[dict]:
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
            "Generate only TECHNICAL ROUND MCQ assessment questions from a Job Description. "
            "Return STRICT JSON only in this format: "
            "{\"questions\":[{\"question\":\"...\",\"options\":[\"...\",\"...\",\"...\",\"...\"],\"correct_option_index\":0}]}. "
            f"Generate exactly {count} questions. "
            "All questions must be answerable from the JD context and role requirements. "
            "Provide exactly 4 options per question and only one correct option. "
            "Do NOT generate HR or behavioral questions like self-introduction, motivation, strengths, weaknesses, or company-fit. "
            "If the role is technical/developer/software, ask technology and implementation questions from JD-required tools/skills. "
            "If the role is management/business/sales/support management, ask management-domain execution questions from JD responsibilities and KPIs."
        )
        context = (
            f"Detected role track: {role_track}\n"
            f"Required skills from JD: {', '.join(required_skills[:12]) or 'none'}\n\n"
            f"Job Description:\n{jd_text[:9000]}"
        )

        max_attempts = min(2, len(model_candidates))
        for model in model_candidates[:max_attempts]:
            try:
                response = model.generate_content(
                    f"{prompt}\n\n{context}",
                    generation_config={"temperature": 0.2, "response_mime_type": "application/json"},
                )
                raw = extract_text(response) or "{}"
                parsed = parse_json_response(raw)
                questions = parsed.get("questions") if isinstance(parsed, dict) else None
                if not isinstance(questions, list):
                    continue

                self.model = model
                filtered: list[dict] = []
                for item in questions:
                    if not isinstance(item, dict):
                        continue
                    question = self._clean_text(item.get("question"), max_len=220)
                    if self._is_behavioral_question(question):
                        continue
                    filtered.append(item)

                return filtered
            except Exception:
                continue

        return []

    def _sanitize_mcq_question_item(self, item: dict) -> dict[str, object] | None:
        question = self._clean_text(item.get("question"), max_len=220)
        if not question:
            return None
        if not question.endswith("?"):
            question = f"{question}?"

        options_raw = item.get("options") if isinstance(item.get("options"), list) else []
        options: list[str] = []
        seen_options: set[str] = set()
        for option in options_raw:
            cleaned_option = self._clean_text(option, max_len=130)
            option_key = self._normalize_term(cleaned_option)
            if not cleaned_option or not option_key or option_key in seen_options:
                continue
            seen_options.add(option_key)
            options.append(cleaned_option)
            if len(options) >= 4:
                break

        if len(options) != 4:
            return None

        try:
            correct_option_index = int(item.get("correct_option_index"))
        except (TypeError, ValueError):
            return None

        if correct_option_index < 0 or correct_option_index > 3:
            return None

        return {
            "question": question,
            "options": options,
            "correct_option_index": correct_option_index,
        }

    def _fallback_mcq_questions(
        self,
        *,
        jd_text: str,
        required_skills: list[str],
        role_track: str,
        count: int,
    ) -> list[dict[str, object]]:
        cleaned_skills = self._clean_skill_output(required_skills, max_items=18)
        if not cleaned_skills:
            cleaned_skills = self._clean_skill_output(self._extract_ranked_terms(jd_text, limit=20), max_items=18)
        if not cleaned_skills:
            cleaned_skills = ["Problem solving", "Communication", "Role responsibilities"]

        is_management = self._is_management_track(role_track, jd_text)
        if is_management:
            distractor_pool = [
                "React component styling",
                "Kernel memory tuning",
                "Compiler design",
                "Mobile GPU optimization",
                "Binary protocol parsing",
                "Database index internals",
                "CSS animation pipelines",
                "Microcontroller flashing",
            ]
            question_templates = [
                "For this management role, which capability is explicitly required in the JD?",
                "According to the JD, which responsibility is most aligned with management execution?",
                "Which of the following reflects a management-side requirement from the uploaded JD?",
                "In this role, which competency should be demonstrated for planning, coordination, or KPI delivery?",
            ]
        else:
            distractor_pool = [
                "Graphic design",
                "Payroll processing",
                "Inventory auditing",
                "Offline marketing",
                "Legal drafting",
                "Event coordination",
                "Video editing",
                "Warehouse operations",
                "Cold calling",
                "Travel planning",
            ]
            question_templates = [
                "For this technical role, which technology is explicitly required in the JD?",
                "According to the uploaded JD, which skill should a candidate demonstrate in projects or internships?",
                "Which of the following is most aligned with the mandatory technical requirements in the JD?",
                "For this software/technical role, which competency is expected for delivery readiness?",
            ]

        questions: list[dict[str, object]] = []
        for index in range(count):
            correct_skill = cleaned_skills[index % len(cleaned_skills)]
            wrong_1 = distractor_pool[index % len(distractor_pool)]
            wrong_2 = distractor_pool[(index + 3) % len(distractor_pool)]
            wrong_3 = cleaned_skills[(index + 1) % len(cleaned_skills)]

            if self._normalize_term(wrong_3) == self._normalize_term(correct_skill):
                wrong_3 = distractor_pool[(index + 5) % len(distractor_pool)]

            options = [wrong_1, wrong_2, wrong_3, correct_skill]
            correct_option_index = index % 4
            options[correct_option_index], options[3] = options[3], options[correct_option_index]

            questions.append(
                {
                    "question": question_templates[index % len(question_templates)],
                    "options": options,
                    "correct_option_index": correct_option_index,
                }
            )

        return questions

    def _is_management_track(self, role_track: str, jd_text: str) -> bool:
        lowered = f"{role_track} {jd_text}".lower()
        return bool(
            re.search(
                r"\b(management|manager|project manager|product manager|operations|business|sales|account|client success|program manager|hr|recruit|customer support lead)\b",
                lowered,
            )
        )

    def _is_behavioral_question(self, question: str) -> bool:
        text = self._normalize_term(question)
        behavioral_tokens = (
            "tell me about yourself",
            "why do you want",
            "strength",
            "weakness",
            "where do you see yourself",
            "questions for us",
            "company",
            "pressure",
            "deadline",
        )
        return any(token in text for token in behavioral_tokens)

    async def generate_resume_questions(self, *, resume_text: str, jd_text: str = "", count: int = 10) -> dict:
        resume_clean = self._normalize(resume_text)
        jd_clean = self._normalize(jd_text)
        requested_count = max(10, min(20, int(count or 10)))

        jd_terms = self._extract_ranked_terms(jd_clean, limit=24)
        required_skills = self._extract_required_skills(jd_clean, jd_terms)
        resume_skills = self._extract_resume_skill_signals(resume_clean, required_skills, max_items=18)
        if not resume_skills:
            resume_skills = self._clean_skill_output(self._extract_ranked_terms(resume_clean, limit=24), max_items=18)

        role_track = self._detect_role_track(jd_clean, resume_clean)

        llm_questions = self._llm_generate_resume_questions(
            resume_text=resume_clean,
            role_track=role_track,
            resume_skills=resume_skills,
            count=requested_count,
        )

        normalized_questions: list[dict[str, str]] = []
        seen_questions: set[str] = set()

        for item in llm_questions:
            sanitized = self._sanitize_resume_question_item(item)
            if not sanitized:
                continue
            question_key = self._normalize_term(str(sanitized["question"]))
            if question_key in seen_questions:
                continue
            seen_questions.add(question_key)
            normalized_questions.append(sanitized)
            if len(normalized_questions) >= requested_count:
                break

        if len(normalized_questions) < requested_count:
            fallback_questions = self._fallback_resume_questions(
                resume_skills=resume_skills,
                role_track=role_track,
                count=requested_count,
            )
            for item in fallback_questions:
                sanitized = self._sanitize_resume_question_item(item)
                if not sanitized:
                    continue
                question_key = self._normalize_term(str(sanitized["question"]))
                if question_key in seen_questions:
                    continue
                seen_questions.add(question_key)
                normalized_questions.append(sanitized)
                if len(normalized_questions) >= requested_count:
                    break

        return {
            "role_track": role_track,
            "questions": normalized_questions[:requested_count],
        }

    def _llm_generate_resume_questions(
        self,
        *,
        resume_text: str,
        role_track: str,
        resume_skills: list[str],
        count: int,
    ) -> list[dict]:
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
            "Generate only RESUME ROUND descriptive interview questions (not MCQ). "
            "Return STRICT JSON only: {\"questions\":[{\"question\":\"...\",\"focus\":\"...\"}]}. "
            f"Return exactly {count} questions. "
            "Questions must be based on skills and technologies explicitly present in the resume. "
            "Do NOT generate HR behavioral questions like self-introduction, strengths, weaknesses, or company motivation."
        )
        context = (
            f"Detected role track: {role_track}\n"
            f"Resume skills: {', '.join(resume_skills[:14]) or 'none'}\n\n"
            f"Resume:\n{resume_text[:9000]}"
        )

        max_attempts = min(2, len(model_candidates))
        for model in model_candidates[:max_attempts]:
            try:
                response = model.generate_content(
                    f"{prompt}\n\n{context}",
                    generation_config={"temperature": 0.2, "response_mime_type": "application/json"},
                )
                raw = extract_text(response) or "{}"
                parsed = parse_json_response(raw)
                questions = parsed.get("questions") if isinstance(parsed, dict) else None
                if not isinstance(questions, list):
                    continue

                self.model = model
                filtered: list[dict] = []
                for item in questions:
                    if not isinstance(item, dict):
                        continue
                    question = self._clean_text(item.get("question"), max_len=220)
                    if self._is_behavioral_question(question):
                        continue
                    filtered.append(item)

                return filtered
            except Exception:
                continue

        return []

    def _sanitize_resume_question_item(self, item: dict) -> dict[str, str] | None:
        question = self._clean_text(item.get("question"), max_len=220)
        if not question:
            return None
        if not question.endswith("?"):
            question = f"{question}?"

        focus = self._clean_text(item.get("focus"), max_len=80)
        return {
            "question": question,
            "focus": focus or "Resume skill application",
        }

    def _fallback_resume_questions(
        self,
        *,
        resume_skills: list[str],
        role_track: str,
        count: int,
    ) -> list[dict[str, str]]:
        skills = self._clean_skill_output(resume_skills, max_items=20)
        if not skills:
            skills = ["problem solving", "communication", "technical execution"]

        is_management = self._is_management_track(role_track, " ".join(skills))
        questions: list[dict[str, str]] = []
        for index in range(count):
            skill = skills[index % len(skills)]
            if is_management:
                templates = [
                    f"Describe a situation where you used {skill} to coordinate people, priorities, or delivery outcomes.",
                    f"How would you apply {skill} to improve KPI tracking or execution quality in a team environment?",
                    f"Explain a resume-based example where {skill} helped you manage stakeholders or workflow decisions.",
                    f"What practical steps would you take to use {skill} for planning and follow-through in this role?",
                ]
            else:
                templates = [
                    f"Explain a real project where you used {skill} and what measurable result you achieved.",
                    f"How would you use {skill} to solve a practical technical problem in this role?",
                    f"What implementation steps do you follow when working with {skill} in projects or internships?",
                    f"From your resume experience, how does {skill} improve system quality, reliability, or performance?",
                ]

            question_text = templates[index % len(templates)]
            focus = f"Skill: {skill}"
            questions.append({"question": question_text, "focus": focus})

        return questions


