import asyncio
import re
from collections import Counter

from app.core.async_utils import run_blocking
from app.config.settings import settings
from app.services.document_parser import chunk_text
from app.services.embedding_service import _cosine_similarity_sync as cosine_similarity, embedding_service
from app.services.gemini_service import (
    _extract_text_sync as extract_text,
    _generation_model_names_sync as generation_model_names,
    _get_model_sync as get_model,
    _parse_json_response_sync as parse_json_response,
)
class AnalysisResumeMixin:
    _ATS_SECTION_HEADINGS = (
        "PROFESSIONAL SUMMARY",
        "WORK EXPERIENCE",
        "PROJECTS",
        "EDUCATION",
        "SKILLS",
        "POSITIONS OF RESPONSIBILITY",
        "CERTIFICATIONS",
    )

    _RESUME_ACTION_VERBS = (
        "Led",
        "Built",
        "Architected",
        "Designed",
        "Developed",
        "Integrated",
        "Implemented",
        "Optimized",
        "Automated",
        "Improved",
        "Reduced",
        "Managed",
        "Coordinated",
        "Selected",
        "Wrote",
        "Applied",
        "Focused",
        "Participated",
        "Contributed",
        "Chosen",
        "Streamlined",
        "Collaborated",
        "Created",
        "Analyzed",
        "Resolved",
    )

    async def generate_ats_resume(
        self,
        *,
        jd_text: str,
        resume_text: str,
        missing_skills: list[str] | None = None,
        target_role: str = "",
        custom_prompt: str = "",
    ) -> dict:
        resume_clean = self._normalize(resume_text)
        jd_clean = self._normalize(jd_text)

        if len(resume_clean.strip()) < 80:
            raise RuntimeError("Resume text is too short for ATS rewrite.")

        requested_role = self._clean_text(target_role, max_len=120) or "Target Role"
        requested_prompt = self._clean_text(custom_prompt, max_len=700)

        jd_terms = self._extract_ranked_terms(jd_clean, limit=26)
        required_skills = self._extract_required_skills(jd_clean, jd_terms)
        resume_signals = self._extract_resume_skill_signals(
            resume_clean,
            required_skills,
            max_items=16,
        )
        missing_focus = self._clean_skill_output(missing_skills or [], max_items=12)
        if not missing_focus:
            missing_focus = self._clean_skill_output(required_skills, max_items=10)

        llm_payload: dict = {}
        rewritten_resume = ""
        uses_llm = False

        if settings.analysis_llm_refinement and self.model is not None:
            llm_payload = await self._llm_generate_ats_resume(
                jd_text=jd_clean,
                resume_text=resume_clean,
                missing_skills=missing_focus,
                resume_skills=resume_signals,
                target_role=requested_role,
                custom_prompt=requested_prompt,
            )
            rewritten_resume = self._build_ats_resume_from_template_payload(
                payload=llm_payload,
                target_role=requested_role,
                resume_text=resume_clean,
                resume_skills=resume_signals,
                missing_skills=missing_focus,
            )
            if not rewritten_resume:
                rewritten_resume = self._clean_generated_resume_text((llm_payload or {}).get("ats_resume"))
            uses_llm = bool(rewritten_resume)
            if rewritten_resume and self._is_resume_layout_malformed(rewritten_resume):
                direct_resume = self._clean_generated_resume_text((llm_payload or {}).get("ats_resume"))
                if direct_resume and not self._is_resume_layout_malformed(direct_resume):
                    rewritten_resume = direct_resume
                else:
                    rewritten_resume = ""
                uses_llm = bool(rewritten_resume)

        if not rewritten_resume:
            rewritten_resume = self._build_fallback_ats_resume(
                resume_text=resume_clean,
                target_role=requested_role,
                missing_skills=missing_focus,
                resume_skills=resume_signals,
            )

        missing_skills_added = self._clean_skill_output(
            (llm_payload or {}).get("missing_skills_added") if isinstance(llm_payload, dict) else [],
            max_items=10,
        )
        if not missing_skills_added:
            missing_skills_added = [
                skill
                for skill in missing_focus
                if not self._contains_term_in_text(skill, resume_clean)
            ][:8]

        improvement_notes = self._clean_string_list(
            (llm_payload or {}).get("improvement_notes") if isinstance(llm_payload, dict) else [],
            max_items=6,
        )
        if not improvement_notes:
            improvement_notes = self._default_resume_upgrade_notes(missing_focus)

        return {
            "target_role": requested_role,
            "ats_resume": rewritten_resume,
            "missing_skills_considered": missing_focus,
            "missing_skills_added": missing_skills_added,
            "improvement_notes": improvement_notes,
            "uses_llm": uses_llm,
        }

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

    async def _llm_generate_ats_resume(
        self,
        *,
        jd_text: str,
        resume_text: str,
        missing_skills: list[str],
        resume_skills: list[str],
        target_role: str,
        custom_prompt: str,
    ) -> dict:
        model = self.model
        if model is None:
            return {}

        source_sections = self._extract_resume_sections(resume_text)
        source_experience_count = len(
            self._extract_experience_from_source(source_sections.get("WORK EXPERIENCE", ""), max_items=10)
        )
        source_projects_count = len(
            self._extract_projects_from_source(source_sections.get("PROJECTS", ""), max_items=10)
        )
        source_positions_count = len(
            self._extract_experience_from_source(
                source_sections.get("POSITIONS OF RESPONSIBILITY", ""),
                max_items=10,
            )
        )

        prompt = (
            "Rewrite the candidate resume into a concise professional ATS resume for the target role. "
            "Return STRICT JSON only. Do not add markdown or code fences. "
            "Required keys: summary (string), experience (array), projects (array), skills (array), education (array), "
            "positions_of_responsibility (array), certifications (array), "
            "missing_skills_added (array), improvement_notes (array). "
            "Rules: use proper sections (Summary, Experience, Projects, Skills, Education), use bullet-ready concise content, "
            "start each bullet idea with strong action verbs (Built, Developed, Designed, Implemented, Optimized), avoid repetition, "
            "keep output realistic, maintain professional tone, and DO NOT use the word 'Delivered'. "
            "Critical rule: preserve all factual candidate data from the source resume. Do not drop or merge role entries incorrectly. "
            "Do not convert structured fields into Python dict strings. "
            "Do not invent fake employers, dates, metrics, certifications, or claims not supported by the resume. "
            "If a missing skill is not evidenced in the resume, include it in missing_skills_added instead of fabricating experience. "
            "For projects, prefer objects with keys: name and bullets (array)."
        )

        context = (
            f"Target role: {target_role}\n"
            f"Missing skills to consider: {', '.join(missing_skills) or 'none'}\n"
            f"Detected resume skills: {', '.join(resume_skills[:12]) or 'none'}\n"
            f"Source experience entries to preserve: {source_experience_count}\n"
            f"Source project entries to preserve: {source_projects_count}\n"
            f"Source responsibility entries to preserve: {source_positions_count}\n"
            f"Custom user instruction: {custom_prompt or 'Rewrite the resume into a professional ATS-friendly format.'}\n\n"
            "JSON template to follow:\n"
            "{\n"
            "  \"summary\": \"\",\n"
            "  \"experience\": [],\n"
            "  \"projects\": [],\n"
            "  \"skills\": [],\n"
            "  \"education\": [],\n"
            "  \"positions_of_responsibility\": [],\n"
            "  \"certifications\": [],\n"
            "  \"missing_skills_added\": [],\n"
            "  \"improvement_notes\": []\n"
            "}\n\n"
            f"Job Description:\n{jd_text[:1800]}\n\n"
            f"Original Resume:\n{resume_text[:4200]}"
        )

        request_text = f"{prompt}\n\n{context}"
        generation_config = {
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "max_output_tokens": 1500,
        }

        try:
            response = await asyncio.wait_for(
                run_blocking(
                    model.generate_content,
                    request_text,
                    generation_config=generation_config,
                    request_options={"timeout": 12},
                ),
                timeout=15,
            )
        except TypeError:
            try:
                response = await asyncio.wait_for(
                    run_blocking(
                        model.generate_content,
                        request_text,
                        generation_config=generation_config,
                    ),
                    timeout=15,
                )
            except Exception:
                return {}
        except Exception:
            return {}

        try:
            raw = extract_text(response) or "{}"
            parsed = parse_json_response(raw)
        except Exception:
            return {}

        return parsed if isinstance(parsed, dict) else {}

    def _build_ats_resume_from_template_payload(
        self,
        *,
        payload: dict,
        target_role: str,
        resume_text: str,
        resume_skills: list[str],
        missing_skills: list[str],
    ) -> str:
        if not isinstance(payload, dict):
            return ""

        sections = self._extract_resume_sections(resume_text)

        summary = self._clean_text(payload.get("summary"), max_len=900)
        if not summary:
            summary = self._clean_text(sections.get("PROFESSIONAL SUMMARY"), max_len=900)

        source_experience_entries = self._extract_experience_from_source(
            sections.get("WORK EXPERIENCE", ""),
            max_items=6,
        )
        experience_entries = self._extract_experience_from_template(payload.get("experience"), max_items=4)
        if not experience_entries:
            experience_entries = source_experience_entries[:4]
        elif source_experience_entries and len(experience_entries) < len(source_experience_entries):
            experience_entries = source_experience_entries[:6]

        source_projects = self._extract_projects_from_source(sections.get("PROJECTS", ""), max_items=8)
        projects = self._extract_projects_from_template(payload.get("projects"), max_items=6)
        if not projects:
            projects = source_projects[:6]
        elif source_projects and len(projects) < len(source_projects):
            projects = source_projects[:8]

        skills = self._clean_string_list(payload.get("skills"), max_items=18)

        education = self._extract_education_from_template(payload.get("education"), max_items=8)
        if not education:
            education = self._extract_education_from_source(
                sections.get("EDUCATION", ""),
                resume_text=resume_text,
            )

        source_positions = self._extract_experience_from_source(
            sections.get("POSITIONS OF RESPONSIBILITY", ""),
            max_items=5,
        )
        positions = self._extract_experience_from_template(
            payload.get("positions_of_responsibility"),
            max_items=4,
        )
        if not positions:
            positions = source_positions[:4]
        elif source_positions and len(positions) < len(source_positions):
            positions = source_positions[:5]

        certifications = self._clean_string_list(payload.get("certifications"), max_items=8)
        if not certifications:
            certifications = self._extract_certifications_from_source(
                sections.get("CERTIFICATIONS", ""),
                resume_text=resume_text,
            )

        if len(experience_entries) < 1:
            fallback_points = self._extract_bullets_from_text(sections.get("WORK EXPERIENCE", ""), max_items=4)
            if not fallback_points:
                fallback_points = [
                    "Implemented role-relevant tasks with clear ownership and quality checks.",
                    "Optimized workflows and improved reliability through practical debugging.",
                ]
            experience_entries = [
                {
                    "title": "Professional Experience",
                    "meta": "",
                    "bullets": fallback_points,
                }
            ]

        if len(projects) < 1:
            projects = [
                {
                    "name": "Project 1",
                    "bullets": [
                        "Built full-stack modules with clear API integration and reusable components.",
                        "Optimized core workflows to improve reliability and maintainability.",
                    ],
                }
            ]

        if not summary:
            summary = (
                "Final-year Computer Science student with practical experience in full-stack development "
                "and building scalable role-relevant solutions."
            )

        has_template_data = any([summary, experience_entries, projects, skills, education])
        if not has_template_data:
            return ""

        header_name, _header_role, header_contact = self._extract_resume_header(resume_text, target_role)
        skills_lines = self._build_skill_lines(
            resume_skills=skills or resume_skills,
            missing_skills=missing_skills,
            source_text=sections.get("SKILLS", "") or resume_text,
        )
        suggested_to_add = self._clean_skill_output(
            payload.get("missing_skills_added") if isinstance(payload, dict) else [],
            max_items=8,
        )

        lines = [
            header_name,
            header_contact,
            "",
            "PROFESSIONAL SUMMARY",
            self._clean_text(summary, max_len=900),
            "",
            "WORK EXPERIENCE",
        ]

        lines.extend(self._render_experience_entries(experience_entries))

        lines.extend(["", "PROJECTS"])
        if projects:
            for project in projects:
                lines.append(project["name"])
                lines.extend([f"- {self._to_action_bullet(bullet)}" for bullet in project["bullets"]])
        else:
            lines.extend(
                [
                    "Project 1",
                    "- Built full-stack modules with clear API integration and reusable components.",
                    "- Optimized core workflows to improve reliability and maintainability.",
                ]
            )

        lines.extend(["", "EDUCATION"])
        if education:
            lines.extend([f"- {self._clean_text(item, max_len=180)}" for item in education[:5]])
        else:
            lines.append("- Bachelor of Technology in Computer Science and Engineering.")

        lines.extend(["", "SKILLS"])
        lines.extend([f"- {item.lstrip('- ').strip()}" for item in skills_lines])

        if positions:
            lines.extend(["", "POSITIONS OF RESPONSIBILITY"])
            lines.extend(self._render_experience_entries(positions))

        if certifications:
            lines.extend(["", "CERTIFICATIONS"])
            lines.extend([f"- {self._clean_text(item, max_len=160)}" for item in certifications[:6]])

        return self._clean_generated_resume_text("\n".join(lines))

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

    def _clean_generated_resume_text(self, value) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()

        normalized = text.replace("\r\n", "\n").replace("\r", "\n")

        normalized = self._recover_section_boundaries(normalized)

        lines = [line.rstrip() for line in normalized.split("\n")]
        compacted: list[str] = []
        last_blank = False
        seen_content: set[str] = set()
        for line in lines:
            normalized_line = re.sub(r"[ \t]+", " ", line).strip()
            normalized_line = self._sanitize_resume_line(normalized_line)
            is_blank = not normalized_line
            if is_blank and last_blank:
                continue
            if not is_blank and normalized_line.upper() not in self._ATS_SECTION_HEADINGS:
                key = re.sub(r"^[\-•*]\s+", "", normalized_line).lower()
                if key in seen_content:
                    continue
                seen_content.add(key)
            compacted.append(normalized_line)
            last_blank = is_blank

        cleaned = "\n".join(compacted).strip()
        return self._truncate_multiline_text(cleaned, max_len=12000)

    def _sanitize_resume_line(self, line: str) -> str:
        text = str(line or "").strip()
        if not text:
            return ""

        text = re.sub(
            r"\bdelivered\b",
            lambda match: "Developed" if match.group(0)[:1].isupper() else "developed",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\b[Bb]uilt\s+architected\b", "Architected", text)
        text = re.sub(r"\b(\w+)(\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip()

    def _extract_resume_sections(self, resume_text: str) -> dict[str, str]:
        raw = str(resume_text or "")
        if not raw.strip():
            return {}

        normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"[ \t]+", " ", normalized)

        # Insert canonical headings into flattened text to preserve section boundaries.
        heading_map: list[tuple[str, str]] = [
            ("PROFESSIONAL SUMMARY", "PROFESSIONAL SUMMARY"),
            ("PROFILE", "PROFESSIONAL SUMMARY"),
            ("WORK EXPERIENCE", "WORK EXPERIENCE"),
            ("PROJECTS", "PROJECTS"),
            ("SKILLS", "SKILLS"),
            ("EDUCATION", "EDUCATION"),
            ("POSITIONS OF RESPONSIBILITY", "POSITIONS OF RESPONSIBILITY"),
            ("CERTIFICATIONS", "CERTIFICATIONS"),
            ("CERTIFICATES", "CERTIFICATIONS"),
        ]

        for source_heading, canonical_heading in heading_map:
            normalized = re.sub(
                rf"(?<![A-Za-z]){re.escape(source_heading)}(?![A-Za-z])",
                f"\n{canonical_heading}\n",
                normalized,
                flags=re.IGNORECASE,
            )

        sections: dict[str, list[str]] = {}
        current = ""
        for raw_line in normalized.split("\n"):
            line = re.sub(r"\s+", " ", raw_line).strip(" -:")
            if not line:
                continue

            upper = line.upper()
            if upper in {
                "PROFESSIONAL SUMMARY",
                "WORK EXPERIENCE",
                "PROJECTS",
                "SKILLS",
                "EDUCATION",
                "POSITIONS OF RESPONSIBILITY",
                "CERTIFICATIONS",
            }:
                current = upper
                sections.setdefault(current, [])
                continue

            if current:
                sections.setdefault(current, []).append(line)

        return {
            section: re.sub(r"\s+", " ", "\n".join(content)).strip()
            for section, content in sections.items()
            if content
        }

    def _extract_experience_from_template(self, value, *, max_items: int) -> list[dict[str, str | list[str]]]:
        if not isinstance(value, list):
            return []

        entries: list[dict[str, str | list[str]]] = []
        for item in value[:max_items]:
            if isinstance(item, dict):
                role = self._clean_text(item.get("role") or item.get("title"), max_len=120)
                company = self._clean_text(item.get("company"), max_len=150)
                location = self._clean_text(item.get("location"), max_len=80)
                duration = self._clean_text(item.get("duration") or item.get("dates"), max_len=80)
                bullets = self._clean_string_list(
                    item.get("bullets")
                    or item.get("points")
                    or item.get("highlights")
                    or item.get("description"),
                    max_items=5,
                )

                title = " - ".join([part for part in [role, company] if part])
                meta = " | ".join([part for part in [location, duration] if part])
                if not title and not bullets:
                    continue
                entries.append(
                    {
                        "title": title or role or company or "Experience",
                        "meta": meta,
                        "bullets": bullets[:5] or ["Built role-relevant execution outcomes with practical ownership."],
                    }
                )
                continue

            text = self._clean_text(item, max_len=260)
            if text:
                entries.append({"title": text, "meta": "", "bullets": []})

        return entries

    def _extract_education_from_template(self, value, *, max_items: int) -> list[str]:
        if value is None:
            return []

        items = value if isinstance(value, list) else [value]
        lines: list[str] = []

        for item in items[:max_items]:
            if isinstance(item, dict):
                degree = self._clean_text(item.get("degree") or item.get("program"), max_len=160)
                institution = self._clean_text(item.get("institution") or item.get("college") or item.get("university"), max_len=160)
                location = self._clean_text(item.get("location"), max_len=80)
                cgpa = self._clean_text(item.get("cgpa") or item.get("grade"), max_len=40)
                duration = self._clean_text(item.get("duration") or item.get("dates") or item.get("year"), max_len=80)

                if degree:
                    lines.append(degree)
                if institution:
                    lines.append(f"{institution}{', ' + location if location else ''}")
                if cgpa:
                    lines.append(f"CGPA: {cgpa}" if not cgpa.lower().startswith("cgpa") else cgpa)
                if duration:
                    lines.append(duration if duration.lower().startswith("duration") else f"Duration: {duration}")
                continue

            text = self._clean_text(item, max_len=180)
            if text and "{" not in text and "}" not in text:
                lines.append(text)

        return self._merge_unique(lines, max_items=max_items)

    def _extract_experience_from_source(self, section_text: str, *, max_items: int) -> list[dict[str, str | list[str]]]:
        text = self._clean_text(section_text, max_len=7000)
        if not text:
            return []

        date_pattern = re.compile(r"\b\d{2}/\d{4}\s*[–-]\s*(?:\d{2}/\d{4}|present)\b", flags=re.IGNORECASE)
        role_hints = ("intern", "developer", "engineer", "executive", "manager", "analyst", "member", "lead")
        entries: list[dict[str, str | list[str]]] = []

        dated_entry_pattern = re.compile(
            r"(?P<title>[A-Z][A-Za-z/&() .\-]{2,60},\s*[A-Z][A-Za-z0-9&() .\-]{2,120})\s*"
            r"(?P<body>.*?)"
            r"(?P<date>\d{2}/\d{4}\s*[–-]\s*(?:\d{2}/\d{4}|present))"
            r"(?:\s*(?P<location>[A-Za-z][A-Za-z .\-]{1,30}))?"
            r"(?=(?:\s+[A-Z][A-Za-z/&() .\-]{2,60},\s*[A-Z][A-Za-z0-9&() .\-]{2,120})|$)",
            flags=re.IGNORECASE,
        )

        for match in dated_entry_pattern.finditer(text):
            title = self._clean_text(match.group("title"), max_len=150)
            if not any(hint in title.lower() for hint in role_hints):
                continue
            body = self._clean_text(match.group("body"), max_len=520)
            date_text = self._clean_text(match.group("date"), max_len=80)
            meta = f"🗓 {date_text}" if date_text else ""

            bullets = self._extract_bullets_from_text(body, max_items=4)
            if not bullets:
                bullets = ["Built role-relevant execution outcomes with practical ownership."]

            entries.append({"title": title, "meta": meta, "bullets": bullets})
            if len(entries) >= max_items:
                return entries

        if entries:
            return entries

        dashed_title_pattern = re.compile(
            r"(?P<title>[A-Z][A-Za-z/&() .\-]{2,80}\s*[–-]\s*[A-Za-z0-9&() .\-]{2,120})\s*(?P<body>.*?)"
            r"(?=(?:[A-Z][A-Za-z/&() .\-]{2,80}\s*[–-]\s*[A-Za-z0-9&() .\-]{2,120})|$)",
            flags=re.IGNORECASE,
        )
        for match in dashed_title_pattern.finditer(text):
            title = self._clean_text(match.group("title"), max_len=150)
            if not any(hint in title.lower() for hint in role_hints):
                continue
            body = self._clean_text(match.group("body"), max_len=520)
            date_match = date_pattern.search(body)
            meta = f"🗓 {date_match.group(0)}" if date_match else ""
            body = date_pattern.sub("", body).strip(" -")

            bullets = self._extract_bullets_from_text(body, max_items=4)
            if not bullets:
                bullets = ["Built role-relevant execution outcomes with practical ownership."]

            entries.append({"title": title, "meta": meta, "bullets": bullets})
            if len(entries) >= max_items:
                return entries

        if entries:
            return entries

        fallback_bullets = self._extract_bullets_from_text(text, max_items=5)
        if fallback_bullets:
            entries.append({"title": "Experience", "meta": "", "bullets": fallback_bullets})

        return entries

    def _extract_projects_from_source(self, section_text: str, *, max_items: int) -> list[dict[str, list[str] | str]]:
        text = self._clean_text(section_text, max_len=9000)
        if not text:
            return []

        matches = list(re.finditer(r"([A-Z][A-Za-z0-9&+\- /]{2,90})\s*,?\s*\(([^)]{2,40})\)", text))
        projects: list[dict[str, list[str] | str]] = []

        if matches:
            for idx, match in enumerate(matches[:max_items]):
                start = match.end()
                end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
                body = text[start:end]
                bullets = self._extract_bullets_from_text(body, max_items=4)
                if len(bullets) < 2:
                    bullets = self._merge_unique(
                        bullets + ["Built role-relevant project features with practical implementation focus."],
                        max_items=4,
                    )
                projects.append({"name": self._clean_text(match.group(1), max_len=90), "bullets": bullets[:4]})
            return projects

        return []

    def _extract_bullets_from_text(self, text: str, *, max_items: int) -> list[str]:
        parts = [
            re.sub(r"^[\-•*]\s*", "", fragment).strip()
            for fragment in re.split(r"\n+|(?<=[.!?])\s+", str(text or ""))
            if fragment.strip()
        ]

        bullets: list[str] = []
        for part in parts:
            candidate = self._clean_text(part, max_len=220)
            if not candidate or len(candidate.split()) < 4:
                continue
            bullets.append(self._to_action_bullet(candidate))
            if len(bullets) >= max_items:
                break

        return self._merge_unique(bullets, max_items=max_items)

    def _extract_education_from_source(self, section_text: str, *, resume_text: str) -> list[str]:
        source = " ".join(filter(None, [section_text, resume_text]))
        lines: list[str] = []

        degree_match = re.search(r"(Bachelor\s+of\s+Technology[^,\n]*|B\.\s?Tech[^,\n]*)", source, flags=re.IGNORECASE)
        if degree_match:
            lines.append(self._clean_text(degree_match.group(1), max_len=140))

        university_match = re.search(r"(Medi-?Caps\s+University[^,\n]*)", source, flags=re.IGNORECASE)
        if university_match:
            lines.append(self._clean_text(university_match.group(1), max_len=140))

        cgpa_match = re.search(r"\bCGPA\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\b", source, flags=re.IGNORECASE)
        if cgpa_match:
            lines.append(f"CGPA: {cgpa_match.group(1)}")

        date_match = re.search(r"\b(20\d{2})\s*[–-]\s*(20\d{2}|Present)\b", source, flags=re.IGNORECASE)
        if date_match:
            lines.append(f"Duration: {date_match.group(1)} - {date_match.group(2)}")

        return self._merge_unique(lines, max_items=5)

    def _extract_certifications_from_source(self, section_text: str, *, resume_text: str) -> list[str]:
        source = section_text or resume_text
        chunks = [
            self._clean_text(item, max_len=140)
            for item in re.split(r"\n+|(?<=[.!?])\s+", source)
            if self._clean_text(item, max_len=140)
        ]
        filtered = [
            item
            for item in chunks
            if re.search(r"hackathon|campaign|participant|certificat", item, flags=re.IGNORECASE)
        ]
        return self._merge_unique(filtered, max_items=6)

    def _render_experience_entries(self, entries: list[dict[str, str | list[str]]]) -> list[str]:
        rendered: list[str] = []
        for entry in entries:
            title = self._clean_text(entry.get("title"), max_len=140)
            meta = self._clean_text(entry.get("meta"), max_len=140)
            raw_bullets = entry.get("bullets") if isinstance(entry.get("bullets"), list) else []
            bullets = self._clean_string_list(raw_bullets, max_items=5)

            if not bullets and title.lower() in {"experience", "professional experience"}:
                continue

            if title:
                rendered.append(title)
            if meta:
                rendered.append(meta)
            rendered.extend([f"- {self._to_action_bullet(bullet)}" for bullet in bullets])
            rendered.append("")

        while rendered and not rendered[-1]:
            rendered.pop()
        return rendered

    def _extract_projects_from_template(self, value, *, max_items: int) -> list[dict[str, list[str] | str]]:
        if not isinstance(value, list):
            return []

        projects: list[dict[str, list[str] | str]] = []
        for item in value[:max_items]:
            if isinstance(item, dict):
                name = self._clean_text(item.get("name") or item.get("title"), max_len=100)
                bullets = self._clean_string_list(
                    item.get("bullets") or item.get("points") or item.get("highlights"),
                    max_items=4,
                )
                description = self._clean_text(item.get("description"), max_len=220)
                if description and not bullets:
                    bullets = [description]
                if not name and not bullets:
                    continue
                projects.append(
                    {
                        "name": name or f"Project {len(projects) + 1}",
                        "bullets": (bullets[:4] or ["Built and improved role-relevant project workflows."])
                        + (["Optimized implementation quality through testing and iteration."] if len(bullets[:4] or ["Built and improved role-relevant project workflows."]) < 2 else []),
                    }
                )
                continue

            item_text = self._clean_text(item, max_len=240)
            if not item_text:
                continue

            if ":" in item_text and len(item_text.split(":", 1)[0].split()) <= 8:
                name_part, bullet_part = item_text.split(":", 1)
                name = self._clean_text(name_part, max_len=100)
                bullet = self._clean_text(bullet_part, max_len=220)
                if not name:
                    name = f"Project {len(projects) + 1}"
                projects.append(
                    {
                        "name": name,
                        "bullets": [bullet, "Optimized implementation quality through testing and iteration."] if bullet else ["Built and improved role-relevant project workflows.", "Optimized implementation quality through testing and iteration."],
                    }
                )
            else:
                projects.append(
                    {
                        "name": f"Project {len(projects) + 1}",
                        "bullets": [item_text, "Optimized implementation quality through testing and iteration."],
                    }
                )

        return projects

    def _build_fallback_ats_resume(
        self,
        *,
        resume_text: str,
        target_role: str,
        missing_skills: list[str],
        resume_skills: list[str],
    ) -> str:
        sections = self._extract_resume_sections(resume_text)
        resume_bullets = self._extract_resume_bullets(resume_text, max_items=8)

        header_name, _header_role, header_contact = self._extract_resume_header(resume_text, target_role)
        role_label = self._clean_text(target_role, max_len=120) or "Target Role"

        summary_line = self._clean_text(sections.get("PROFESSIONAL SUMMARY"), max_len=900)
        if not summary_line:
            summary_seed = resume_bullets[0].replace(".", "").strip() if resume_bullets else "full-stack project execution"
            summary_line = (
                f"Final-year Computer Science candidate targeting {role_label} with practical experience in {summary_seed}."
            )

        experience_entries = self._extract_experience_from_source(
            sections.get("WORK EXPERIENCE", ""),
            max_items=4,
        )
        if not experience_entries:
            fallback_points = resume_bullets[:4] or [
                "Implemented role-relevant tasks with clear ownership and quality checks.",
                "Optimized workflows and improved reliability through practical debugging.",
            ]
            experience_entries = [{"title": "Professional Experience", "meta": "", "bullets": fallback_points}]

        project_entries = self._extract_projects_from_source(sections.get("PROJECTS", ""), max_items=6)
        if not project_entries:
            project_entries = self._extract_project_entries(resume_text, resume_bullets)

        education_lines = self._extract_education_from_source(
            sections.get("EDUCATION", ""),
            resume_text=resume_text,
        )
        if not education_lines:
            education_lines = ["Bachelor of Technology in Computer Science and Engineering."]

        skills_lines = self._build_skill_lines(
            resume_skills=resume_skills,
            missing_skills=missing_skills,
            source_text=sections.get("SKILLS", "") or resume_text,
        )

        positions = self._extract_experience_from_source(
            sections.get("POSITIONS OF RESPONSIBILITY", ""),
            max_items=3,
        )
        certifications = self._extract_certifications_from_source(
            sections.get("CERTIFICATIONS", ""),
            resume_text=resume_text,
        )

        lines = [
            header_name,
            header_contact,
            "",
            "PROFESSIONAL SUMMARY",
            summary_line,
            "",
            "WORK EXPERIENCE",
        ]
        lines.extend(self._render_experience_entries(experience_entries))

        lines.extend(["", "PROJECTS"])
        for entry in project_entries:
            lines.append(entry["name"])
            lines.extend([f"- {self._to_action_bullet(bullet)}" for bullet in entry["bullets"]])

        lines.extend(["", "SKILLS"])
        lines.extend([f"- {item}" for item in skills_lines])

        lines.extend(["", "EDUCATION"])
        lines.extend([f"- {self._clean_text(item, max_len=180)}" for item in education_lines[:5]])

        if positions:
            lines.extend(["", "POSITIONS OF RESPONSIBILITY"])
            lines.extend(self._render_experience_entries(positions))

        if certifications:
            lines.extend(["", "CERTIFICATIONS"])
            lines.extend([f"- {self._clean_text(item, max_len=160)}" for item in certifications[:6]])

        return self._clean_generated_resume_text("\n".join(lines))

    def _truncate_multiline_text(self, text: str, *, max_len: int) -> str:
        raw = str(text or "")
        if len(raw) <= max_len:
            return raw

        window = raw[: max_len + 1]
        cut = window.rfind("\n")
        if cut < max(40, int(max_len * 0.6)):
            cut = window.rfind(" ")
        if cut <= 0:
            cut = max_len
        return window[:cut].rstrip()

    def _extract_resume_bullets(self, resume_text: str, *, max_items: int) -> list[str]:
        raw_text = self._normalize(resume_text)
        fragments = [
            item.strip(" -•\t")
            for item in re.split(r"\n+|(?<=[.!?])\s+", raw_text)
            if str(item or "").strip()
        ]

        cleaned: list[str] = []
        seen: set[str] = set()
        for fragment in fragments:
            candidate = re.sub(r"\s+", " ", fragment).strip()
            if len(candidate) < 28 or len(candidate) > 240:
                continue
            lowered = candidate.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(self._to_action_bullet(candidate))
            if len(cleaned) >= max_items:
                break

        return cleaned

    def _to_action_bullet(self, text: str) -> str:
        sentence = re.sub(r"\s+", " ", str(text or "")).strip(" -•\t")
        if not sentence:
            return ""

        sentence = re.sub(r"^(i|we|my team)\s+", "", sentence, flags=re.IGNORECASE)
        sentence = sentence.rstrip(".;:")

        first_word = sentence.split(" ", 1)[0].lower() if sentence.split() else ""
        action_verbs = {verb.lower() for verb in self._RESUME_ACTION_VERBS}
        if first_word not in action_verbs:
            sentence = f"Built {sentence[:1].lower() + sentence[1:] if len(sentence) > 1 else sentence}"

        if not sentence.endswith("."):
            sentence = f"{sentence}."
        return sentence

    def _default_resume_upgrade_notes(self, missing_skills: list[str]) -> list[str]:
        notes = [
            "Bullets were rewritten with stronger action verbs for ATS readability.",
            "Resume content was organized into ATS-friendly sections with concise language.",
            "JD-aligned keywords were emphasized to improve role relevance.",
        ]
        if missing_skills:
            notes.append(
                f"Missing skills considered in rewrite: {', '.join(missing_skills[:5])}."
            )
        return self._merge_unique(notes, max_items=6)

    def _recover_section_boundaries(self, text: str) -> str:
        normalized = str(text or "")
        dense = normalized.count("\n") < 6

        if not dense:
            return normalized

        for heading in self._ATS_SECTION_HEADINGS:
            normalized = re.sub(
                rf"(?<![a-z]){re.escape(heading)}(?![a-z])",
                f"\n\n{heading}\n",
                normalized,
            )
        return normalized

    def _is_resume_layout_malformed(self, text: str) -> bool:
        parsed = self._parse_resume_sections(text)
        required = ["PROFESSIONAL SUMMARY", "WORK EXPERIENCE", "PROJECTS", "SKILLS"]
        if any(section not in parsed for section in required):
            return True

        if len(parsed.get("WORK EXPERIENCE", [])) < 2:
            return True
        if len(parsed.get("PROJECTS", [])) < 3:
            return True

        skills_content = " ".join(parsed.get("SKILLS", []))
        if len(skills_content) < 24:
            return True

        stripped_lines = [line.strip() for line in str(text or "").split("\n") if line.strip()]
        if any(line in {".", ":", "-"} for line in stripped_lines):
            return True

        return False

    def _parse_resume_sections(self, text: str) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {}
        current = ""

        for raw in str(text or "").split("\n"):
            line = raw.strip()
            if not line:
                continue

            upper = line.upper()
            if upper in self._ATS_SECTION_HEADINGS:
                current = upper
                sections.setdefault(current, [])
                continue

            if current:
                sections.setdefault(current, []).append(line)

        return sections

    def _extract_resume_header(self, resume_text: str, target_role: str) -> tuple[str, str, str]:
        text = str(resume_text or "")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        name = "CANDIDATE NAME"
        role = self._clean_text(target_role, max_len=120) or "Target Role"
        contact = "Email: candidate.email@example.com | Phone: +00 0000000000"

        name_match = re.search(r"\b([A-Z]{2,}(?:\s+[A-Z]{2,}){1,3})\b", text)
        if name_match:
            name = self._clean_text(name_match.group(1), max_len=80)

        email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.IGNORECASE)
        phone_match = re.search(r"(?:\+\d{1,3}[\s-]?)?\d{10}", text)
        linkedin_match = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/[A-Za-z0-9_\-./]+", text, flags=re.IGNORECASE)
        github_match = re.search(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_\-./]+", text, flags=re.IGNORECASE)

        contact_parts: list[str] = []
        if email_match:
            contact_parts.append(f"📧 {email_match.group(0)}")
        if phone_match:
            raw_phone = phone_match.group(0)
            if raw_phone and not raw_phone.startswith("+") and len(re.sub(r"\D", "", raw_phone)) == 10:
                raw_phone = f"+91-{raw_phone[-10:]}"
            contact_parts.append(f"📞 {raw_phone}")
        if contact_parts:
            contact = " | ".join(contact_parts)

        social_parts: list[str] = []
        if linkedin_match:
            social_parts.append(
                f"LinkedIn: {linkedin_match.group(0).replace('https://', '').replace('http://', '')}"
            )
        if github_match:
            social_parts.append(
                f"GitHub: {github_match.group(0).replace('https://', '').replace('http://', '')}"
            )
        if social_parts:
            contact = "\n".join([contact, f"🔗 {' | '.join(social_parts)}"])

        if lines and not name_match:
            first = lines[0]
            if len(first.split()) <= 5:
                name = first.upper()

        for line in lines[:10]:
            lowered = line.lower()
            if len(line.split()) <= 12 and any(
                token in lowered for token in ["developer", "engineer", "analyst", "intern", "specialist"]
            ):
                role = self._clean_text(line, max_len=120)
                break

        return name.upper(), role, contact

    def _extract_project_entries(self, resume_text: str, resume_bullets: list[str]) -> list[dict[str, list[str] | str]]:
        lines = [line.strip() for line in str(resume_text or "").replace("\r", "").split("\n") if line.strip()]
        entries: list[dict[str, list[str] | str]] = []
        in_projects = False
        current: dict[str, list[str] | str] | None = None

        for line in lines:
            upper = line.upper()
            if upper == "PROJECTS":
                in_projects = True
                current = None
                continue
            if in_projects and upper in self._ATS_SECTION_HEADINGS and upper != "PROJECTS":
                break
            if not in_projects:
                continue

            if self._looks_like_project_name(line):
                if current:
                    entries.append(current)
                current = {"name": line, "bullets": []}
                continue

            if current is None:
                continue

            cleaned = re.sub(r"^[\-•*]\s+", "", line).strip()
            if cleaned:
                current["bullets"].append(self._to_action_bullet(cleaned))

        if current:
            entries.append(current)

        filtered = []
        for entry in entries[:4]:
            bullets = [str(item).strip() for item in list(entry.get("bullets") or []) if str(item).strip()]
            if len(bullets) < 2:
                bullets.extend(resume_bullets[: max(0, 2 - len(bullets))])
            filtered.append({"name": str(entry.get("name") or "Project").strip(), "bullets": bullets[:4]})

        if filtered:
            return filtered

        return [
            {
                "name": "Project 1",
                "bullets": resume_bullets[:2] if resume_bullets else [
                    "Developed a production-ready application with modular backend architecture.",
                    "Implemented APIs and data models to support scalable feature delivery.",
                ],
            },
            {
                "name": "Project 2",
                "bullets": resume_bullets[2:4] if len(resume_bullets) >= 4 else [
                    "Built role-based workflows with clean data validation and error handling.",
                    "Improved usability and performance through iterative optimization.",
                ],
            },
        ]

    def _looks_like_project_name(self, line: str) -> bool:
        text = str(line or "").strip()
        if not text:
            return False
        if len(text) > 80:
            return False
        if text.endswith(":"):
            return False
        if text.lower().startswith("languages") or text.lower().startswith("tools"):
            return False
        if re.search(r"\b(\d{4}|present|cgpa|university|intern|developer\s*\|)\b", text, flags=re.IGNORECASE):
            return False

        words = text.split()
        return 1 <= len(words) <= 8

    def _build_skill_lines(
        self,
        *,
        resume_skills: list[str],
        missing_skills: list[str],
        source_text: str = "",
    ) -> list[str]:
        source = f"{' '.join(resume_skills)} {' '.join(missing_skills)} {source_text}".lower()

        def _pick(candidates: list[tuple[str, str]]) -> list[str]:
            picked: list[str] = []
            for label, pattern in candidates:
                if re.search(pattern, source, flags=re.IGNORECASE):
                    picked.append(label)
            return picked

        languages = _pick(
            [
                ("Python", r"\bpython\b"),
                ("Java", r"\bjava\b"),
                ("HTML", r"\bhtml\b"),
                ("CSS", r"\bcss\b"),
                ("JavaScript", r"\bjavascript\b"),
                ("TypeScript", r"\btypescript\b"),
            ]
        )
        frontend = _pick(
            [
                ("React (Vite)", r"\breact\b|\bvite\b"),
                ("Tailwind CSS", r"\btailwind\b"),
            ]
        )
        backend = _pick(
            [
                ("FastAPI", r"\bfastapi\b"),
                ("MongoDB", r"\bmongodb\b"),
                ("MySQL", r"\bmysql\b"),
                ("REST APIs", r"\brest\s*apis?\b|\bapis?\b"),
            ]
        )
        ai_stack = _pick(
            [
                ("Prompt Engineering", r"prompt"),
                ("RAG", r"\brag\b|context"),
                ("OpenAI/Gemini APIs", r"openai|gemini|llm"),
                ("Text Processing", r"text\s*parsing|text\s*processing|semantic"),
            ]
        )
        tools = _pick(
            [
                ("Git", r"\bgit\b"),
                ("GitHub", r"github"),
                ("VS Code", r"vs\s*code|vscode|visual\s*studio\s*code"),
                ("Postman", r"postman"),
                ("Figma", r"figma"),
            ]
        )

        if not languages:
            languages = ["Python", "Java", "HTML", "CSS"]
        if not frontend:
            frontend = ["React (Vite)", "Tailwind CSS"]
        if not backend:
            backend = ["FastAPI", "MongoDB", "REST APIs"]
        if not tools:
            tools = ["Git", "GitHub", "Postman"]

        lines = [
            f"Languages: {', '.join(languages[:6])}",
            f"Frontend: {', '.join(frontend[:4])}",
            f"Backend & Database: {', '.join(backend[:6])}",
        ]
        if ai_stack:
            lines.append(f"AI/LLM: {', '.join(ai_stack[:5])}")
        lines.append(f"Tools: {', '.join(tools[:6])}")

        return lines


