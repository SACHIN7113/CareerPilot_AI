import re
from collections import Counter

from app.config.settings import settings
from app.services.document_parser import _chunk_text_sync as chunk_text
from app.services.embedding_service import _cosine_similarity_sync as cosine_similarity, embedding_service
from app.services.gemini_service import (
    _extract_text_sync as extract_text,
    _get_model_sync as get_model,
    _parse_json_response_sync as parse_json_response,
)
class AnalysisMatchMixin:
    async def analyze_match(
        self,
        *,
        jd_text: str,
        resume_text: str,
        practice_answers: list[dict[str, str]] | None = None,
    ) -> dict:
        jd_clean = self._normalize(jd_text)
        resume_clean = self._normalize(resume_text)

        jd_terms = self._extract_ranked_terms(jd_clean, limit=24)
        required_skills = self._prune_redundant_skills(
            self._extract_required_skills(jd_text, jd_terms),
            max_items=12,
        )
        normalized_practice_answers = self._normalize_practice_answers(practice_answers)
        practice_evaluation = self._evaluate_practice_answers(
            answers=normalized_practice_answers,
            required_skills=required_skills,
            jd_terms=jd_terms,
        )
        rag_context = self._build_rag_context(
            jd_text=jd_text,
            resume_text=resume_text,
            required_skills=required_skills,
            jd_terms=jd_terms,
        )
        resume_scope = self._normalize("\n".join(filter(None, [rag_context["resume_context"], resume_clean])))

        resume_terms = self._extract_ranked_terms(resume_scope, limit=80)
        resume_lookup = set(resume_terms)

        alternative_groups = self._extract_skill_alternative_groups(jd_text, required_skills)
        satisfied_alternative_keys = self._resolve_satisfied_alternative_keys(
            alternative_groups=alternative_groups,
            resume_lookup=resume_lookup,
            resume_text=resume_scope,
        )

        def _skill_explicit_match(skill: str) -> bool:
            return self._contains_skill(skill, resume_lookup, resume_scope)

        def _skill_satisfied(skill: str) -> bool:
            if _skill_explicit_match(skill):
                return True
            skill_key = self._skill_key(skill)
            if skill_key and skill_key in satisfied_alternative_keys:
                return True
            return False

        matched_required = [
            skill for skill in required_skills if _skill_explicit_match(skill)
        ]
        missing_required = [
            skill for skill in required_skills if not _skill_satisfied(skill)
        ]

        hard_required_skills = [skill for skill in required_skills if self._is_hard_skill(skill)]
        coverage_required_skills = hard_required_skills if len(hard_required_skills) >= 3 else required_skills
        matched_coverage_required = [skill for skill in coverage_required_skills if _skill_satisfied(skill)]

        matched = [term for term in jd_terms if _skill_explicit_match(term)][:12]
        missing = [term for term in jd_terms if not _skill_satisfied(term)][:12]

        critical_candidates = [skill for skill in required_skills if self._is_hard_skill(skill)]
        if not critical_candidates:
            critical_candidates = [
                skill
                for skill in self._extract_critical_requirements(jd_text, jd_terms)
                if self._is_hard_skill(skill)
            ]

        critical_jd_skills = self._sanitize_critical_skills(
            critical_candidates or required_skills or self._extract_critical_requirements(jd_text, jd_terms)
        )
        critical_jd_skills = self._prune_redundant_skills(critical_jd_skills, max_items=12)
        critical_missing = [
            skill for skill in critical_jd_skills if not _skill_satisfied(skill)
        ]
        critical_penalty_units = self._critical_penalty_units(critical_missing)

        required_coverage = (
            len(matched_coverage_required) / max(1, len(coverage_required_skills))
            if coverage_required_skills
            else 0.0
        )
        critical_coverage = (
            len([skill for skill in critical_jd_skills if _skill_satisfied(skill)]) / max(1, len(critical_jd_skills))
            if critical_jd_skills
            else required_coverage
        )
        keyword_coverage = len(matched) / max(1, len(jd_terms))
        semantic_score = self._semantic_similarity(
            rag_context["jd_context"] or jd_clean,
            rag_context["resume_context"] or resume_clean,
        )
        baseline_score = int(
            round(
                (
                    critical_coverage * 0.40
                    + required_coverage * 0.30
                    + keyword_coverage * 0.15
                    + semantic_score * 0.15
                )
                * 100
            )
        )

        should_use_llm = self._should_use_llm_refinement(
            required_coverage=required_coverage,
            critical_coverage=critical_coverage,
            keyword_coverage=keyword_coverage,
            semantic_score=semantic_score,
            critical_missing_count=len(critical_missing),
        )

        llm_result: dict = {}
        llm_refinement_warning = ""
        if should_use_llm:
            try:
                llm_result = self._llm_structured_analysis(
                    jd_text=jd_clean,
                    resume_text=resume_clean,
                    rag_jd_context=rag_context["jd_context"],
                    rag_resume_context=rag_context["resume_context"],
                    practice_context=practice_evaluation["practice_context"],
                    practice_score=practice_evaluation["practice_score"],
                    baseline_score=baseline_score,
                    heuristic_matched=self._merge_unique(matched_required + matched, max_items=12),
                    heuristic_missing=self._merge_unique(missing_required + missing, max_items=12),
                    critical_jd_skills=critical_jd_skills,
                    critical_missing_skills=critical_missing,
                )
            except RuntimeError as exc:
                if settings.analysis_llm_refinement:
                    llm_refinement_warning = (
                        "LLM refinement was unavailable, so heuristic analysis was used for this result."
                    )
                llm_result = {}

        llm_score_raw = self._as_score((llm_result or {}).get("overall_score"), baseline_score)
        if llm_result:
            delta_cap = 14 if required_coverage >= 0.50 else 20
            bounded_llm_score = max(baseline_score - delta_cap, min(baseline_score + delta_cap, llm_score_raw))
            overall_score = int(round((baseline_score * 0.60) + (bounded_llm_score * 0.40)))
        else:
            overall_score = baseline_score

        llm_critical_missing = llm_result.get("critical_missing_skills") or []
        critical_missing_skills = self._sanitize_critical_skills(
            self._merge_unique(critical_missing + llm_critical_missing, max_items=12)
        )
        critical_missing_skills = [
            skill
            for skill in critical_missing_skills
            if self._is_hard_skill(skill)
            and self._skill_key(skill) not in satisfied_alternative_keys
            and not _skill_satisfied(skill)
        ]
        critical_missing_skills = self._prune_redundant_skills(critical_missing_skills, max_items=12)

        overall_score = self._apply_critical_penalty(int(overall_score), self._critical_penalty_units(critical_missing_skills))
        verdict = self._score_to_verdict(overall_score)
        if critical_missing_skills and verdict == "Strong Match":
            verdict = "Moderate Match"
        if self._critical_penalty_units(critical_missing_skills) >= 4:
            verdict = "Low Match"

        matched_keywords = self._merge_unique(
            (llm_result.get("matched_keywords") or []) + matched_required + matched,
            max_items=12,
        )
        llm_missing_keywords = [
            item
            for item in (llm_result.get("missing_keywords") or [])
            if self._skill_key(item) not in satisfied_alternative_keys and not _skill_satisfied(item)
        ]
        missing_seed = missing_required if required_skills else missing
        missing_keywords = self._merge_unique(missing_seed + llm_missing_keywords + critical_missing_skills, max_items=12)

        matched_skills = self._clean_skill_output(matched_required + matched_keywords, max_items=12)
        missing_skills = self._clean_skill_output(missing_required + missing_keywords, max_items=12)
        missing_skills = self._merge_unique(critical_missing_skills + missing_skills, max_items=12)

        if not matched_skills:
            matched_skills = self._clean_skill_output(matched_keywords, max_items=12)
        if not missing_skills:
            missing_skills = self._clean_skill_output(missing_keywords, max_items=12)

        matched_skills, missing_skills, critical_missing_skills = self._reconcile_skill_lists(
            matched_skills,
            missing_skills,
            critical_missing_skills,
        )

        # Missing section should include all important gaps, including critical gaps.
        missing_skills = self._merge_unique(critical_missing_skills + missing_skills, max_items=12)
        matched_skills = self._prune_redundant_skills(matched_skills, max_items=12)
        missing_skills = self._prune_redundant_skills(missing_skills, max_items=12)
        critical_missing_skills = self._prune_redundant_skills(critical_missing_skills, max_items=12)

        matched_keywords = matched_skills
        missing_keywords = missing_skills

        role_track = self._detect_role_track(jd_clean, resume_clean)
        resume_role_keywords = self._extract_resume_role_keywords(
            resume_scope=resume_scope,
            resume_terms=resume_terms,
            required_skills=required_skills,
            jd_terms=jd_terms,
            role_track=role_track,
            matched_skills=matched_skills,
        )

        low_match_reasons = self._build_low_match_reasons(
            overall_score=overall_score,
            critical_missing_skills=critical_missing_skills,
            missing_skills=missing_skills,
            practice_score=practice_evaluation["practice_score"],
        )
        suggested_roles = self._suggest_alternative_roles(
            matched_skills=matched_skills,
            resume_terms=resume_terms,
            practice_context=practice_evaluation["practice_context"],
        )
        role_fit_advice = self._build_role_fit_advice(
            verdict=verdict,
            suggested_roles=suggested_roles,
            low_match_reasons=low_match_reasons,
        )

        jd_key_points = llm_result.get("jd_key_points") or self._extract_key_points(jd_text, limit=5)
        resume_highlights = llm_result.get("resume_highlights") or self._extract_key_points(resume_text, limit=5)
        recommendations = llm_result.get("recommendations") or self._build_recommendations(missing_keywords, critical_missing_skills)
        recommendations = self._merge_unique(recommendations + practice_evaluation["practice_feedback"], max_items=6)
        if llm_refinement_warning:
            recommendations = self._merge_unique(recommendations + [llm_refinement_warning], max_items=6)
        summary = llm_result.get("summary") or (
            f"Resume to JD match is {overall_score}%. Matched {len(matched_keywords)} key requirement areas."
        )
        summary = self._align_summary_with_score(
            summary=summary,
            overall_score=overall_score,
            verdict=verdict,
            role_fit_advice=role_fit_advice,
            low_match_reasons=low_match_reasons,
        )

        return {
            "overall_score": max(0, min(100, int(overall_score))),
            "verdict": verdict,
            "matched_keywords": matched_keywords[:12],
            "missing_keywords": missing_keywords[:12],
            "resume_role_keywords": resume_role_keywords[:12],
            "matched_skills": matched_skills[:12],
            "missing_skills": missing_skills[:12],
            "critical_missing_skills": critical_missing_skills[:12],
            "low_match_reasons": low_match_reasons[:5],
            "suggested_roles": suggested_roles[:3],
            "role_fit_advice": role_fit_advice,
            "practice_score": practice_evaluation["practice_score"],
            "practice_feedback": practice_evaluation["practice_feedback"][:4],
            "jd_key_points": jd_key_points[:6],
            "resume_highlights": resume_highlights[:6],
            "recommendations": recommendations[:6],
            "summary": summary[:350],
            "uses_llm": bool(llm_result),
            "uses_rag": rag_context["uses_rag"],
        }

    def _llm_structured_analysis(
        self,
        *,
        jd_text: str,
        resume_text: str,
        rag_jd_context: str,
        rag_resume_context: str,
        practice_context: str,
        practice_score: int,
        baseline_score: int,
        heuristic_matched: list[str],
        heuristic_missing: list[str],
        critical_jd_skills: list[str],
        critical_missing_skills: list[str],
    ) -> dict:
        prompt = (
            "You are an ATS + recruiter assistant. Compare Job Description and Resume with evidence-based judgement. "
            "Missing required JD skills should reduce the score clearly, but avoid double-penalizing minor gaps. "
            "Only count skills as matched when resume evidence is explicit. "
            "Return STRICT JSON only with these keys: "
            "overall_score (0-100 int), verdict (Strong Match|Moderate Match|Low Match), "
            "critical_missing_skills (array of short strings, only mandatory JD skills missing in resume), "
            "matched_keywords (array of concrete skill names), missing_keywords (array of required skills truly missing), "
            "jd_key_points (array), resume_highlights (array), recommendations (array), summary (string max 70 words). "
            "Do not use markdown, do not add extra keys."
        )
        rag_note = (
            "Use the retrieved evidence snippets as primary grounding for match/missing decisions. "
            "If a skill is not in retrieved evidence, verify against the full resume before marking it missing."
            if rag_jd_context and rag_resume_context
            else ""
        )
        context = (
            f"Baseline score from embedding+keywords: {baseline_score}\n"
            f"Heuristic matched keywords: {', '.join(heuristic_matched) or 'none'}\n"
            f"Heuristic missing keywords: {', '.join(heuristic_missing) or 'none'}\n\n"
            f"Critical JD skills (mandatory/high-priority): {', '.join(critical_jd_skills) or 'none'}\n"
            f"Critical missing skills detected: {', '.join(critical_missing_skills) or 'none'}\n"
            f"Practice mode score (candidate HR responses): {practice_score}\n"
            f"Practice mode response summary: {practice_context[:1200] or 'none'}\n"
            f"{rag_note}\n\n"
            f"RAG retrieved JD evidence:\n{rag_jd_context[:2600] or 'none'}\n\n"
            f"RAG retrieved Resume evidence:\n{rag_resume_context[:3000] or 'none'}\n\n"
            f"Job Description:\n{jd_text[:4500]}\n\n"
            f"Resume:\n{resume_text[:5000]}"
        )

        parsed = None
        last_error: Exception | None = None
        model_candidates = []
        if self.model is not None:
            model_candidates.append(self.model)
        for model_name in self._candidate_model_names():
            model = get_model(model_name)
            if model is not None:
                model_candidates.append(model)

        max_attempts = 1 if settings.analysis_fast_mode else len(model_candidates)
        for model in model_candidates[:max_attempts]:
            try:
                response = model.generate_content(
                    f"{prompt}\n\n{context}",
                    generation_config={"temperature": 0.1, "response_mime_type": "application/json"},
                )
                raw = extract_text(response) or "{}"
                parsed = parse_json_response(raw)
                self.model = model
                break
            except Exception as exc:
                last_error = exc

        if parsed is None:
            message = str(last_error or "Unknown LLM failure")
            if "resource_exhausted" in message.lower() or "quota" in message.lower() or "429" in message:
                raise RuntimeError("LLM quota exceeded for configured model(s). Update GEMINI_MODEL or billing/quota.")
            raise RuntimeError(f"LLM analysis request failed: {message[:180]}")

        overall_score = self._as_score(parsed.get("overall_score"), baseline_score)
        verdict = self._normalize_verdict(parsed.get("verdict"), overall_score)

        return {
            "overall_score": overall_score,
            "verdict": verdict,
            "critical_missing_skills": self._clean_string_list(parsed.get("critical_missing_skills"), max_items=12),
            "matched_keywords": self._clean_string_list(parsed.get("matched_keywords"), max_items=12),
            "missing_keywords": self._clean_string_list(parsed.get("missing_keywords"), max_items=12),
            "jd_key_points": self._clean_string_list(parsed.get("jd_key_points"), max_items=6),
            "resume_highlights": self._clean_string_list(parsed.get("resume_highlights"), max_items=6),
            "recommendations": self._clean_string_list(parsed.get("recommendations"), max_items=6),
            "summary": self._clean_text(parsed.get("summary"), max_len=350),
        }

    def _contains_skill(self, term: str, resume_lookup: set[str], resume_text: str) -> bool:
        normalized_term = self._normalize_term(term)
        if not normalized_term:
            return False

        term_key = self._skill_key(term)
        canonical_pattern = self._CANONICAL_SKILL_PATTERNS.get(term_key)
        if canonical_pattern and re.search(canonical_pattern, resume_text, flags=re.IGNORECASE):
            return True

        if normalized_term in {self._normalize_term(item) for item in resume_lookup}:
            return True

        normalized_resume = self._normalize_term(resume_text)
        if normalized_term and normalized_term in normalized_resume:
            return True

        words = [part for part in normalized_term.split(" ") if len(part) >= 3]
        if len(words) >= 2 and all(word in normalized_resume for word in words):
            return True

        return False

    def _extract_skill_alternative_groups(self, jd_text: str, required_skills: list[str]) -> list[list[str]]:
        text = jd_text or ""
        required_map = {self._skill_key(skill): skill for skill in required_skills}
        groups: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()

        for left, right in re.findall(
            r"\b([A-Za-z0-9+#.\-]{2,})\s*(?:/|\bor\b)\s*([A-Za-z0-9+#.\-]{2,})\b",
            text,
            flags=re.IGNORECASE,
        ):
            left_text = self._clean_text(left, max_len=80)
            right_text = self._clean_text(right, max_len=80)
            left_key = self._skill_key(left_text)
            right_key = self._skill_key(right_text)
            if not left_key or not right_key or left_key == right_key:
                continue

            left_skill = required_map.get(left_key, left_text)
            right_skill = required_map.get(right_key, right_text)
            if not (self._is_hard_skill(left_skill) or self._is_hard_skill(right_skill)):
                continue

            group_keys = tuple(sorted({self._skill_key(left_skill), self._skill_key(right_skill)}))
            if len(group_keys) < 2 or group_keys in seen:
                continue

            seen.add(group_keys)
            groups.append([left_skill, right_skill])

        # Common equivalent DB requirements should be treated as alternatives even without explicit '/' or 'or'.
        known_alternative_pairs = [("mysql", "postgresql")]
        for left_key, right_key in known_alternative_pairs:
            if left_key not in required_map or right_key not in required_map:
                continue
            group_keys = tuple(sorted({left_key, right_key}))
            if group_keys in seen:
                continue
            seen.add(group_keys)
            groups.append([required_map[left_key], required_map[right_key]])

        return groups[:8]

    def _resolve_satisfied_alternative_keys(
        self,
        *,
        alternative_groups: list[list[str]],
        resume_lookup: set[str],
        resume_text: str,
    ) -> set[str]:
        satisfied: set[str] = set()

        for group in alternative_groups:
            if any(self._contains_skill(skill, resume_lookup, resume_text) for skill in group):
                for skill in group:
                    skill_key = self._skill_key(skill)
                    if skill_key:
                        satisfied.add(skill_key)

        return satisfied

    def _should_use_llm_refinement(
        self,
        *,
        required_coverage: float,
        critical_coverage: float,
        keyword_coverage: float,
        semantic_score: float,
        critical_missing_count: int,
    ) -> bool:
        _ = required_coverage
        _ = critical_coverage
        _ = keyword_coverage
        _ = semantic_score
        _ = critical_missing_count

        if not settings.analysis_llm_refinement:
            return False

        # LLM is mandatory for analysis when refinement is enabled.
        return True

    def _normalize_practice_answers(self, answers: list[dict[str, str]] | None) -> list[dict[str, str]]:
        if not isinstance(answers, list):
            return []

        normalized: list[dict[str, str]] = []
        for index, item in enumerate(answers[:8]):
            if not isinstance(item, dict):
                continue

            question = self._clean_text(item.get("question") or f"Question {index + 1}", max_len=220)
            answer = self._clean_text(item.get("answer"), max_len=1500)
            if not answer:
                continue

            normalized.append({"question": question, "answer": answer})

        return normalized

    def _evaluate_practice_answers(
        self,
        *,
        answers: list[dict[str, str]],
        required_skills: list[str],
        jd_terms: list[str],
    ) -> dict:
        if not answers:
            return {
                "practice_score": 0,
                "practice_feedback": [
                    "Complete practice mode answers for stronger HR-readiness and role-fit evaluation."
                ],
                "practice_context": "",
            }

        answer_texts = [item["answer"] for item in answers if item.get("answer")]
        answer_blob = self._normalize(" ".join(answer_texts))
        word_counts = [len(text.split()) for text in answer_texts]
        avg_words = sum(word_counts) / max(1, len(word_counts))

        concise_ratio = sum(1 for count in word_counts if count >= 10) / max(1, len(word_counts))
        depth_ratio = sum(1 for count in word_counts if count >= 20) / max(1, len(word_counts))

        referenced_required = [
            skill for skill in required_skills if self._contains_term_in_text(skill, answer_blob)
        ]
        referenced_terms = [
            term for term in jd_terms[:12] if self._contains_term_in_text(term, answer_blob)
        ]

        aligned_items = self._clean_skill_output(referenced_required + referenced_terms, max_items=10)
        alignment_ratio = min(
            1.0,
            len(aligned_items) / max(1, min(6, len(required_skills) if required_skills else 6)),
        )

        motivation_hits = sum(
            1
            for token in self._MOTIVATION_TOKENS
            if re.search(rf"\b{re.escape(token)}\b", answer_blob, flags=re.IGNORECASE)
        )
        motivation_ratio = min(1.0, motivation_hits / 4)

        practice_score = int(
            round((concise_ratio * 0.35 + depth_ratio * 0.20 + alignment_ratio * 0.30 + motivation_ratio * 0.15) * 100)
        )
        practice_score = max(0, min(100, practice_score))

        feedback: list[str] = []
        if practice_score >= 75:
            feedback.append("Practice answers are strong and role-oriented.")
        elif practice_score >= 50:
            feedback.append("Practice answers are decent but need more role-specific depth.")
        else:
            feedback.append("Practice answers are currently too generic for this role.")

        if len(answer_texts) < 5:
            feedback.append("Try answering at least 5 HR practice questions before final analysis.")
        if avg_words < 14:
            feedback.append("Use richer examples in each answer (projects, outcomes, ownership).")

        if aligned_items:
            feedback.append(f"You already referenced: {', '.join(aligned_items[:4])}.")
        else:
            target_examples = self._clean_skill_output(required_skills or jd_terms[:6], max_items=4)
            if target_examples:
                feedback.append(f"Explicitly connect your answers to required skills like: {', '.join(target_examples)}.")

        practice_context = self._normalize(
            " ".join(f"{item['question']}: {item['answer']}" for item in answers)
        )[:1800]

        return {
            "practice_score": practice_score,
            "practice_feedback": self._merge_unique(feedback, max_items=4),
            "practice_context": practice_context,
        }

    def _contains_term_in_text(self, term: str, text: str) -> bool:
        normalized_text = self._normalize_term(text)
        if not normalized_text:
            return False

        term_key = self._skill_key(term)
        canonical_pattern = self._CANONICAL_SKILL_PATTERNS.get(term_key)
        if canonical_pattern and re.search(canonical_pattern, text, flags=re.IGNORECASE):
            return True

        normalized_term = self._normalize_term(term)
        if not normalized_term:
            return False

        if normalized_term in normalized_text:
            return True

        words = [word for word in normalized_term.split(" ") if len(word) >= 3]
        return len(words) >= 2 and all(word in normalized_text for word in words)

    def _clean_skill_output(
        self,
        skills: list[str] | tuple[str, ...] | set[str] | str | None,
        *,
        max_items: int,
    ) -> list[str]:
        if skills is None:
            return []
        if isinstance(skills, str):
            source_items = [skills]
        elif isinstance(skills, (list, tuple, set)):
            source_items = list(skills)
        else:
            return []

        cleaned: list[str] = []
        seen: set[str] = set()

        for skill in source_items:
            text = self._clean_text(skill, max_len=120)
            key = self._skill_key(text)
            if not text or not key or key in seen:
                continue
            if key in self._STOP_WORDS or key in self._CRITICAL_NOISE_TERMS:
                continue
            if self._is_non_skill_key(key):
                continue
            if len(key.split(" ")) == 1:
                if key in self._GENERIC_NOISE_TOKENS:
                    continue
                if key not in self._TECH_HINT_TOKENS and key not in self._CANONICAL_SKILL_PATTERNS:
                    continue
            if len(key) < 2:
                continue

            seen.add(key)
            cleaned.append(text)
            if len(cleaned) >= max_items:
                break

        return cleaned

    def _build_low_match_reasons(
        self,
        *,
        overall_score: int,
        critical_missing_skills: list[str],
        missing_skills: list[str],
        practice_score: int,
    ) -> list[str]:
        reasons: list[str] = []

        if overall_score < 60:
            reasons.append("Overall alignment is below the usual shortlist threshold for this role.")

        if critical_missing_skills:
            reasons.append(f"Mandatory JD skills are missing: {', '.join(critical_missing_skills[:4])}.")

        remaining_missing = [
            skill
            for skill in missing_skills
            if self._skill_key(skill) not in {self._skill_key(item) for item in critical_missing_skills}
        ]
        if remaining_missing:
            reasons.append(f"Additional required skills need stronger resume evidence: {', '.join(remaining_missing[:4])}.")

        if practice_score < 55:
            reasons.append("Practice-mode HR answers need clearer role-specific examples.")

        return self._merge_unique(reasons, max_items=5)

    def _suggest_alternative_roles(
        self,
        *,
        matched_skills: list[str],
        resume_terms: list[str],
        practice_context: str,
    ) -> list[str]:
        candidate_signals: set[str] = set()

        for skill in matched_skills:
            key = self._skill_key(skill)
            if key:
                candidate_signals.add(key)

        preferred_terms = {self._skill_key(item) for item in self._SKILL_PHRASES}
        for term in resume_terms[:40]:
            key = self._skill_key(term)
            if not key:
                continue
            if key in self._TECH_HINT_TOKENS or key in preferred_terms:
                candidate_signals.add(key)

        for term in self._extract_ranked_terms(practice_context, limit=20):
            key = self._skill_key(term)
            if key and key not in self._STOP_WORDS:
                candidate_signals.add(key)

        role_scores: list[tuple[int, str]] = []
        for role, skills in self._ROLE_SKILL_MAP.items():
            role_keys = {self._skill_key(skill) for skill in skills}
            overlap = len(role_keys.intersection(candidate_signals))
            if overlap >= 2:
                role_scores.append((overlap, role))

        role_scores.sort(key=lambda item: (-item[0], item[1]))
        return [role for _score, role in role_scores[:3]]

    def _extract_resume_role_keywords(
        self,
        *,
        resume_scope: str,
        resume_terms: list[str],
        required_skills: list[str],
        jd_terms: list[str],
        role_track: str,
        matched_skills: list[str],
    ) -> list[str]:
        role_skills = list(self._ROLE_SKILL_MAP.get(role_track, set()))

        required_hits = [skill for skill in required_skills if self._contains_term_in_text(skill, resume_scope)]
        role_hits = [skill for skill in role_skills if self._contains_term_in_text(skill, resume_scope)]
        jd_hits = [
            term
            for term in jd_terms[:20]
            if self._is_hard_skill(term) and self._contains_term_in_text(term, resume_scope)
        ]
        resume_hard_terms = [term for term in resume_terms[:40] if self._is_hard_skill(term)]

        merged = self._merge_unique(
            matched_skills + required_hits + role_hits + jd_hits + resume_hard_terms,
            max_items=24,
        )
        return self._clean_skill_output(merged, max_items=12)

    def _build_role_fit_advice(
        self,
        *,
        verdict: str,
        suggested_roles: list[str],
        low_match_reasons: list[str],
    ) -> str:
        if verdict == "Strong Match":
            return "You are a strong fit for this role. Focus on presenting measurable project impact in interviews."

        if verdict == "Moderate Match":
            if suggested_roles:
                return self._clean_text(
                    f"You are a partial fit for this role. You may also fit roles like {', '.join(suggested_roles[:2])}.",
                    max_len=220,
                )
            return "You are a partial fit for this role. Strengthen missing required skills to improve interview chances."

        if suggested_roles:
            return self._clean_text(
                f"You are not a strong fit for this role yet. Based on your current skills, you are better aligned with: {', '.join(suggested_roles)}.",
                max_len=260,
            )

        if low_match_reasons:
            return self._clean_text(
                f"You are not a strong fit for this role yet. Main reason: {low_match_reasons[0]}",
                max_len=240,
            )

        return "You are not a strong fit for this role yet. Build stronger evidence for required skills first."

    def _align_summary_with_score(
        self,
        *,
        summary: str,
        overall_score: int,
        verdict: str,
        role_fit_advice: str,
        low_match_reasons: list[str],
    ) -> str:
        text = self._clean_text(summary, max_len=260)

        contradiction_patterns = (
            r"\bstrong\s+(?:candidate|fit|match)\b",
            r"\bexcellent\s+(?:fit|match)\b",
            r"\bhigh(?:ly)?\s+aligned\b",
            r"\bwell\s+aligned\b",
        )

        if overall_score < 45 or verdict == "Low Match":
            lead = f"Current match is {overall_score}%. You are a developing fit for this role."
            primary_gap = low_match_reasons[0] if low_match_reasons else "Important required JD skills are still missing."
            detail = f"Main gap: {primary_gap}"
            result = self._clean_text(f"{lead} {detail}", max_len=300)
            if role_fit_advice:
                result = self._clean_text(f"{result} {role_fit_advice}", max_len=350)
            return result

        if overall_score < 70 or verdict == "Moderate Match":
            for pattern in contradiction_patterns:
                text = re.sub(pattern, "partial fit", text, flags=re.IGNORECASE)
            if role_fit_advice and "partial fit" in text.lower() and role_fit_advice.lower() not in text.lower():
                text = self._clean_text(f"{text} {role_fit_advice}", max_len=350)
            return text

        return self._clean_text(text, max_len=350)

    def _extract_critical_requirements(self, jd_text: str, ranked_terms: list[str]) -> list[str]:
        critical: list[str] = []
        text = jd_text or ""
        lowered = text.lower()

        trigger_pattern = re.compile(
            r"\b(?:must|required|mandatory|need(?:s)? to|should have|strong experience|hands[- ]on|essential)\b",
            flags=re.IGNORECASE,
        )

        for phrase in self._SKILL_PHRASES:
            escaped = re.escape(phrase)
            phrase_pattern = re.compile(
                rf"(?:{trigger_pattern.pattern}.{{0,70}}\b{escaped}\b|\b{escaped}\b.{{0,45}}{trigger_pattern.pattern})",
                flags=re.IGNORECASE,
            )
            if phrase_pattern.search(lowered):
                critical.append(phrase)

        sentences = [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+|\n+", text) if chunk.strip()]
        for sentence in sentences:
            if not trigger_pattern.search(sentence):
                continue
            for term in self._extract_ranked_terms(sentence, limit=10):
                if len(term) >= 3:
                    critical.append(term)

        if not critical:
            critical = ranked_terms[:6]

        return self._merge_unique(critical, max_items=12)

    def _extract_required_skills(self, jd_text: str, ranked_terms: list[str]) -> list[str]:
        text = jd_text or ""
        lines = [line.strip() for line in re.split(r"\r\n?|\n", text) if line.strip()]

        required_lines: list[str] = []
        in_required_section = False

        for raw_line in lines:
            line = raw_line.strip()
            lower = line.lower()

            if any(marker in lower for marker in self._REQUIRED_SECTION_MARKERS):
                in_required_section = True
                continue

            if in_required_section and any(marker in lower for marker in self._SECTION_BREAK_MARKERS):
                in_required_section = False

            if in_required_section:
                cleaned = re.sub(r"^[\-•*\d.)\s]+", "", line).strip()
                if cleaned:
                    required_lines.append(cleaned)

            if re.search(r"(?i)\b(?:must|required|mandatory|essential|should have|need(?:s)? to)\b", line):
                required_lines.append(re.sub(r"^[\-•*\d.)\s]+", "", line).strip())

        extracted: list[str] = []
        for sentence in required_lines:
            extracted.extend(self._extract_skills_from_text(sentence))

        if not extracted:
            extracted = [term for term in ranked_terms if self._is_hard_skill(term)][:8]
        if not extracted:
            extracted = ranked_terms[:8]

        sanitized = self._sanitize_critical_skills(self._merge_unique(extracted, max_items=12))
        return self._clean_skill_output(sanitized, max_items=12)

    def _extract_skills_from_text(self, text: str) -> list[str]:
        lowered = (text or "").lower()
        skills: list[str] = []

        for skill, pattern in self._CANONICAL_SKILL_PATTERNS.items():
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                skills.append(skill)

        for phrase in self._SKILL_PHRASES:
            if phrase in lowered:
                skills.append(phrase)

        for token in self._extract_ranked_terms(lowered, limit=8):
            if token in self._TECH_HINT_TOKENS:
                skills.append(token)

        return self._merge_unique(skills, max_items=12)

    def _sanitize_critical_skills(self, skills: list[str]) -> list[str]:
        sanitized: list[str] = []
        for skill in skills:
            text = self._clean_text(skill, max_len=120)
            if not self._is_valid_critical_skill(text):
                continue
            sanitized.append(text)
        return self._merge_unique(sanitized, max_items=12)

    def _is_valid_critical_skill(self, skill: str) -> bool:
        normalized = self._normalize_term(skill)
        if not normalized:
            return False

        if self._is_non_skill_key(self._skill_key(skill)):
            return False

        if normalized in self._CRITICAL_NOISE_TERMS:
            return False

        words = [w for w in normalized.split(" ") if w]
        if not words:
            return False

        if len(words) == 1 and words[0] in self._CRITICAL_NOISE_TERMS:
            return False

        if all(word in self._STOP_WORDS or word in self._CRITICAL_NOISE_TERMS for word in words):
            return False

        if len(normalized) < 4:
            return False

        return True

    def _build_rag_context(
        self,
        *,
        jd_text: str,
        resume_text: str,
        required_skills: list[str],
        jd_terms: list[str],
    ) -> dict:
        jd_source = self._normalize(jd_text)
        resume_source = self._normalize(resume_text)
        if settings.analysis_fast_mode:
            jd_source = jd_source[:12000]
            resume_source = resume_source[:14000]

        jd_chunks = chunk_text(jd_source, chunk_size=self._RAG_CHUNK_SIZE, overlap=self._RAG_CHUNK_OVERLAP)
        resume_chunks = chunk_text(resume_source, chunk_size=self._RAG_CHUNK_SIZE, overlap=self._RAG_CHUNK_OVERLAP)
        queries = self._build_rag_queries(required_skills, jd_terms)

        if not jd_chunks or not resume_chunks or not queries:
            return {"jd_context": "", "resume_context": "", "uses_rag": False}

        jd_top_k = 4 if settings.analysis_fast_mode else self._RAG_JD_TOP_K
        resume_top_k = 5 if settings.analysis_fast_mode else self._RAG_RESUME_TOP_K

        jd_ranked = self._rank_chunks_for_queries(jd_chunks, queries, top_k=jd_top_k)
        resume_ranked = self._rank_chunks_for_queries(resume_chunks, queries, top_k=resume_top_k)

        jd_context = "\n\n".join(chunk for _score, _index, chunk in jd_ranked)
        resume_context = "\n\n".join(chunk for _score, _index, chunk in resume_ranked)

        return {
            "jd_context": self._normalize(jd_context),
            "resume_context": self._normalize(resume_context),
            "uses_rag": bool(jd_context and resume_context),
        }

    def _build_rag_queries(self, required_skills: list[str], jd_terms: list[str]) -> list[str]:
        queries: list[str] = []
        max_required_queries = 4 if settings.analysis_fast_mode else 10
        for skill in required_skills[:max_required_queries]:
            normalized = self._clean_text(skill, max_len=120)
            if normalized:
                queries.append(f"Evidence for required skill: {normalized}")

        if jd_terms:
            queries.append(f"Primary JD keywords: {', '.join(jd_terms[:8])}")
            if settings.analysis_fast_mode:
                queries.append(f"Role scope summary: {', '.join(jd_terms[:4])}")

        if not queries:
            queries.append("Core required skills and role expectations")

        max_queries = 6 if settings.analysis_fast_mode else 14
        return self._merge_unique(queries, max_items=max_queries)

    def _rank_chunks_for_queries(
        self,
        chunks: list[str],
        queries: list[str],
        *,
        top_k: int,
    ) -> list[tuple[float, int, str]]:
        if not chunks or not queries:
            return []

        chunk_embeddings = [self._embed_with_fallback(chunk, task_type="retrieval_document") for chunk in chunks]

        best_scores = [-1.0] * len(chunks)
        for query in queries:
            query_embedding = self._embed_with_fallback(query, task_type="retrieval_query")
            for index, chunk_embedding in enumerate(chunk_embeddings):
                score = cosine_similarity(query_embedding, chunk_embedding)
                if score > best_scores[index]:
                    best_scores[index] = score

        ranked = sorted(
            ((best_scores[index], index, chunks[index]) for index in range(len(chunks))),
            key=lambda item: (-item[0], item[1]),
        )

        if not ranked:
            return []

        selected = ranked[: max(1, min(top_k, len(ranked)))]
        return [
            (score, index, self._clean_text(chunk, max_len=1800))
            for score, index, chunk in selected
            if self._clean_text(chunk, max_len=1800)
        ]

    def _embed_with_fallback(self, text: str, *, task_type: str) -> list[float]:
        try:
            return embedding_service._embed_sync(text, task_type=task_type)
        except TypeError:
            return embedding_service._embed_sync(text)

    def _critical_penalty_units(self, critical_missing_skills: list[str]) -> int:
        hard = sum(1 for skill in critical_missing_skills if self._is_hard_skill(skill))
        soft = max(0, len(critical_missing_skills) - hard)

        # Keep strictness for large hard-skill gaps, but avoid over-penalizing 1-2 misses.
        if hard <= 2:
            hard_units = hard
        else:
            hard_units = 2 + ((hard - 2 + 1) // 2)

        soft_units = 1 if soft >= 4 else 0
        return hard_units + soft_units

    def _is_hard_skill(self, skill: str) -> bool:
        normalized = self._normalize_term(skill)
        if not normalized:
            return False

        if self._skill_key(skill) in self._SOFT_CORE_SKILLS:
            return False

        if normalized in self._SKILL_PHRASES:
            return True

        tokens = set(normalized.split(" "))
        if tokens.intersection(self._TECH_HINT_TOKENS):
            return True

        if re.search(r"\b(?:api|sql|aws|azure|gcp|ml|ai|oop|devops|docker|kubernetes|terraform)\b", normalized):
            return True

        return False

    def _normalize_term(self, value: str) -> str:
        normalized = re.sub(r"[^a-z0-9+#.\-\s]", " ", (value or "").lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _merge_unique(self, items: list[str], *, max_items: int) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = self._clean_text(item, max_len=120)
            key = self._normalize_term(text)
            if not text or not key or key in seen:
                continue
            seen.add(key)
            merged.append(text)
            if len(merged) >= max_items:
                break
        return merged

    def _skill_key(self, value: str) -> str:
        normalized = self._normalize_term(value)
        normalized = normalized.replace("-", " ").replace("/", " ").replace(".", " ")
        normalized = re.sub(r"\bb\s*\.?\s*tech\b", "btech", normalized)
        normalized = re.sub(r"\b(cs\s*/\s*it|cse|cs it)\b", "csit", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _is_non_skill_key(self, key: str) -> bool:
        if not key:
            return True

        if key in self._NON_SKILL_TERMS:
            return True

        if re.search(r"\b(?:btech|degree|graduate|fresher|eligibility|eligible)\b", key):
            return True

        if re.fullmatch(r"(?:cse|csit|computer science(?: degree)?)", key):
            return True

        return False

    def _reconcile_skill_lists(
        self,
        matched_keywords: list[str],
        missing_keywords: list[str],
        critical_missing_skills: list[str],
    ) -> tuple[list[str], list[str], list[str]]:
        matched_clean = self._merge_unique(self._clean_string_list(matched_keywords, max_items=12), max_items=12)
        missing_clean = self._merge_unique(self._clean_string_list(missing_keywords, max_items=12), max_items=12)
        critical_clean = self._merge_unique(
            self._clean_string_list(critical_missing_skills, max_items=12),
            max_items=12,
        )

        matched_keys = {self._skill_key(item) for item in matched_clean if self._skill_key(item)}

        missing_filtered = [item for item in missing_clean if self._skill_key(item) not in matched_keys]
        critical_filtered = [item for item in critical_clean if self._skill_key(item) not in matched_keys]

        return matched_clean[:12], missing_filtered[:12], critical_filtered[:12]

    def _prune_redundant_skills(self, skills: list[str], *, max_items: int) -> list[str]:
        merged = self._merge_unique(self._clean_string_list(skills, max_items=max_items * 2), max_items=max_items * 2)
        keys = [self._skill_key(item) for item in merged]
        key_set = {key for key in keys if key}

        generic_bases = {"testing", "qa", "automation", "support"}

        filtered: list[str] = []
        for item in merged:
            key = self._skill_key(item)
            if not key:
                continue

            has_specific_variant = any(
                other != key and (
                    other.startswith(f"{key} ")
                    or other.endswith(f" {key}")
                    or (key in other.split(" ") and len(other.split(" ")) > 1)
                )
                for other in key_set
            )

            if key in generic_bases and has_specific_variant:
                continue

            filtered.append(item)
            if len(filtered) >= max_items:
                break

        return filtered

    def _apply_critical_penalty(self, score: int, penalty_units: int) -> int:
        if penalty_units <= 0:
            return max(0, min(100, int(score)))

        penalty = min(22, penalty_units * 4)
        penalized = max(18, int(score) - penalty)
        score_cap = max(58, 94 - (penalty_units * 6))
        return min(penalized, score_cap)

    def _semantic_similarity(self, jd_text: str, resume_text: str) -> float:
        if settings.analysis_fast_mode:
            jd_text = (jd_text or "")[:3500]
            resume_text = (resume_text or "")[:4500]

        jd_embedding = embedding_service._embed_sync(jd_text, task_type="retrieval_document")
        resume_embedding = embedding_service._embed_sync(resume_text, task_type="retrieval_query")
        similarity = cosine_similarity(jd_embedding, resume_embedding)
        return max(0.0, min(1.0, (similarity + 1.0) / 2.0))

    def _extract_ranked_terms(self, text: str, *, limit: int) -> list[str]:
        tokens = []
        lower_text = text.lower()
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{2,}", lower_text):
            normalized = token.strip(".-")
            if len(normalized) < 3 or normalized in self._STOP_WORDS:
                continue
            tokens.append(normalized)

        counts = Counter(tokens)

        terms: list[str] = []
        for phrase in self._SKILL_PHRASES:
            if phrase in lower_text:
                terms.append(phrase)

        for token, _freq in counts.most_common(limit * 2):
            if token not in terms:
                terms.append(token)
            if len(terms) >= limit:
                break

        return terms[:limit]

    def _extract_key_points(self, text: str, *, limit: int) -> list[str]:
        normalized = re.sub(r"\r\n?", "\n", text)
        lines = [line.strip(" -\t") for line in normalized.split("\n") if line.strip()]
        candidate_lines = [line for line in lines if len(line.split()) >= 4]
        if not candidate_lines:
            candidate_lines = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]

        points: list[str] = []
        for line in candidate_lines:
            cleaned = re.sub(r"\s+", " ", line).strip()
            if len(cleaned) < 25:
                continue
            if len(cleaned) > 170:
                cleaned = cleaned[:170].rstrip()
            points.append(cleaned)
            if len(points) >= limit:
                break

        return points or ["No clear key points could be extracted."]

    def _build_recommendations(self, missing: list[str], critical_missing: list[str] | None = None) -> list[str]:
        critical_missing = critical_missing or []
        if not missing and not critical_missing:
            return [
                "Resume aligns well with the JD. Keep projects and impact metrics highlighted.",
                "Tailor your top 3 achievements to match role language before applying.",
            ]

        if critical_missing:
            top_critical = ", ".join(critical_missing[:4])
            return [
                f"Address these mandatory JD gaps first: {top_critical}.",
                "Add explicit project bullets proving each required skill with measurable outcomes.",
                "Place required skills in the top summary and corresponding project section for ATS visibility.",
            ]

        top_missing = ", ".join(missing[:4])
        return [
            f"Add stronger evidence for these JD areas: {top_missing}.",
            "Include one project bullet per missing skill with measurable outcome.",
            "Use the same terminology as the JD for ATS and recruiter clarity.",
        ]


