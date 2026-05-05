import hashlib
import re
from typing import Sequence

from app.core.async_utils import run_blocking
from app.services.gemini_service import (
    _extract_text_sync as extract_text,
    _generation_model_names_sync as generation_model_names,
    _get_model_sync as get_model,
    _parse_json_response_sync as parse_json_response,
)


class QuestionEngine:
    _STOP_WORDS = {
        "about",
        "after",
        "again",
        "also",
        "been",
        "being",
        "between",
        "both",
        "could",
        "does",
        "from",
        "have",
        "into",
        "just",
        "more",
        "most",
        "only",
        "other",
        "over",
        "same",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "very",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "would",
        "your",
    }
    _CONCEPT_NOISE = {
        "answer",
        "question",
        "example",
        "document",
        "section",
        "details",
        "project",
    }
    _GENERIC_QUESTION_KEYS = {
        "what is the main idea of this passage",
        "what is the main idea of this document",
        "what is the key concept in this answer",
    }
    _SKILL_PATTERN_MAP = {
        "python": r"\bpython\b",
        "java": r"\bjava\b",
        "c": r"\bc\s*language\b|\bc\s*programming\b|\bc/c\+\+\b",
        "c++": r"\bc\+\+\b|\bcpp\b",
        "javascript": r"\bjavascript\b|\bjs\b",
        "react": r"\breact\b",
        "fastapi": r"\bfastapi\b",
        "html": r"\bhtml\b|\bhtnl\b",
        "css": r"\bcss\b",
        "sql": r"\bsql\b|\bmysql\b|\bpostgres(?:ql)?\b",
        "git": r"\bgit\b|\bgithub\b|\bgitlab\b",
        "docker": r"\bdocker\b",
        "oop": r"\boop\b|\boops\b|\bobject\s*oriented\b",
        "testing": r"\btesting\b|\bqa\b|\bunit test(?:ing)?\b|\bautomation test(?:ing)?\b",
        "communication": r"\bcommunication\b|\binterpersonal\b|\bverbal\b",
        "customer support": r"\bcustomer\s*support\b|\btechnical\s*support\b|\bsupport\s*associate\b",
        "customer communication": r"\bcustomer\b.*\bcommunicat|\bcommunication\b.*\bcustomer\b",
        "ticketing system": r"\bticket(?:ing)?\b|\bservice\s*desk\b|\bincident\b",
        "troubleshooting": r"\btroubleshoot(?:ing)?\b|\bdebug(?:ging)?\b|\bdiagnos(?:e|ing)\b",
        "api": r"\bapi\b|\brest\b",
        "linux": r"\blinux\b|\bunix\b",
        "networking": r"\bnetwork\b|\bdns\b|\btcp\b|\bip\b",
        "problem solving": r"\bproblem[\s-]*solv(?:ing|e)\b|\banalytical\s+thinking\b",
    }
    _SKILL_CURRICULUM = {
        "html": {
            1: [
                (
                    "What is HTML and why is it used in web development?",
                    "HTML (HyperText Markup Language) defines the structure of web pages using elements like headings, paragraphs, links, images, and forms.",
                ),
                (
                    "What is semantic HTML?",
                    "Semantic HTML uses meaningful tags such as header, nav, main, article, section, and footer so content structure is clearer for developers, search engines, and assistive tools.",
                ),
                (
                    "Which common HTML tags should every developer know, and what are they used for?",
                    "Common tags include h1 to h6 for headings, p for paragraphs, a for links, img for images, ul or ol with li for lists, and form with input and button for user input.",
                ),
            ],
            2: [
                (
                    "How do semantic HTML tags improve accessibility and SEO?",
                    "Semantic tags provide better meaning and document structure, which improves screen-reader navigation and helps search engines interpret content hierarchy.",
                ),
            ],
            3: [
                (
                    "How would you structure a semantic HTML page for maintainability at scale?",
                    "Use landmarks such as header, nav, main, section, article, aside, and footer with clear heading hierarchy and reusable components so the document remains readable and easy to maintain.",
                ),
            ],
        },
        "python": {
            1: [
                (
                    "What is Python?",
                    "Python is a high-level interpreted programming language known for readable syntax and fast development.",
                ),
                (
                    "What are key features of Python?",
                    "Key Python features include readable syntax, dynamic typing, rich standard libraries, cross-platform support, and strong ecosystem support for automation, web, and data tasks.",
                ),
                (
                    "What are common Python data types?",
                    "Common Python data types include int, float, bool, str, list, tuple, dict, and set.",
                ),
            ],
            2: [
                (
                    "What is the difference between a list and a tuple in Python?",
                    "A list is mutable and can be changed after creation, while a tuple is immutable and better for fixed collections.",
                ),
            ],
            3: [
                (
                    "How would you choose between list, tuple, set, and dict for a Python task?",
                    "Use list for ordered mutable sequences, tuple for fixed ordered data, set for unique membership checks, and dict for key-value lookups.",
                ),
            ],
        },
        "problem solving": {
            1: [
                (
                    "Problem statement: Given an integer array and a target sum, return two indices whose values add up to the target. How would you solve this efficiently?",
                    "Use a hash map of value to index while scanning once. For each number, check whether target minus number already exists in the map; if yes, return those two indices. This gives O(n) time complexity.",
                ),
                (
                    "Problem statement: Given a string, find the first non-repeating character. What approach would you use?",
                    "Count each character frequency first, then scan the string again and return the first character with count one. This is linear in time with a hash map.",
                ),
            ],
            2: [
                (
                    "Problem statement: Given a list of intervals, merge all overlapping intervals. How would you approach this?",
                    "Sort intervals by start time, then iterate and merge when current start is less than or equal to last merged end. Otherwise, append a new interval.",
                ),
            ],
            3: [
                (
                    "Problem statement: Design an algorithm to detect a cycle in a singly linked list. Which method would you use and why?",
                    "Use Floyd's tortoise-and-hare pointers. Move one pointer by one step and the other by two steps; if they meet, a cycle exists. It runs in O(n) time and O(1) space.",
                ),
            ],
        },
    }
    _TECHNICAL_ROLE_HINTS = {
        "engineer",
        "developer",
        "technical",
        "analyst",
        "admin",
        "qa",
        "sre",
        "devops",
        "it",
    }
    _NON_TECHNICAL_ROLE_HINTS = {
        "sales",
        "hr",
        "recruit",
        "operations",
        "marketing",
        "finance",
        "customer success",
    }
    _TECHNICAL_SKILL_HINTS = {
        "python",
        "java",
        "javascript",
        "html",
        "sql",
        "api",
        "linux",
        "networking",
        "debugging",
        "troubleshooting",
        "automation",
        "problem solving",
    }
    _NONTECHNICAL_SKILL_HINTS = {
        "communication",
        "stakeholder",
        "presentation",
        "planning",
        "negotiation",
        "documentation",
        "coordination",
        "customer",
        "recruitment",
        "campaign",
    }
    _NON_SKILL_NOISE_TOKENS = {
        "bond",
        "security amount",
        "salary",
        "ctc",
        "lpa",
        "stipend",
        "notice period",
        "working days",
        "shift",
        "gross",
        "per month",
        "per annum",
        "marks",
        "percentage",
        "cgpa",
        "board exam",
        "graduation",
        "batch",
        "male candidates",
        "female candidates",
        "age",
        "eligibility",
        "b.tech",
        "btech",
        "m.tech",
        "mtech",
    }
    _ROLE_SKILL_DEFAULTS = {
        "support": ["Troubleshooting", "Ticketing System", "Communication", "Problem Solving"],
        "developer": ["Programming", "Problem Solving", "OOP", "API"],
        "engineer": ["Programming", "Problem Solving", "OOP", "API"],
        "qa": ["Testing", "Problem Solving", "Communication"],
        "tester": ["Testing", "Problem Solving", "Communication"],
        "analyst": ["SQL", "Problem Solving", "Communication"],
    }

    def __init__(self) -> None:
        self.model = get_model()

    def _generate_question_sync(
        self,
        *,
        context: str,
        difficulty: int,
        recent_questions: Sequence[str] | None = None,
        attempt_index: int = 0,
        require_llm: bool = False,
        role_title: str = "",
        required_skills: Sequence[str] | None = None,
        key_requirements: Sequence[str] | None = None,
        resume_skills: Sequence[str] | None = None,
        input_type: str = "jd",
        strict_skill_mode: bool = False,
        resume_text: str = "",
        variation_seed: str = "",
    ) -> tuple[str, str]:
        source = re.sub(r"\s+", " ", (context or "").strip())
        if not source:
            if require_llm:
                raise RuntimeError("Document chunk is empty. Cannot generate LLM question.")
            return (
                "What is the main idea of this document?",
                "The document does not contain enough text to extract a reliable answer.",
            )

        recent = list(recent_questions or [])

        has_profile_metadata = bool(
            role_title.strip()
            or (required_skills or [])
            or (key_requirements or [])
            or (resume_skills or [])
            or resume_text.strip()
        )

        if require_llm:
            llm_question, llm_answer = self._llm_generate_with_model_fallback(
                context=source,
                difficulty=difficulty,
                attempt_index=attempt_index,
                recent_questions=recent,
            )
            return llm_question, llm_answer

        if has_profile_metadata:
            skill_question, skill_answer = self._skill_focused_generate(
                context=source,
                difficulty=difficulty,
                recent_questions=recent,
                attempt_index=attempt_index,
                role_title=role_title,
                required_skills=required_skills or [],
                key_requirements=key_requirements or [],
                resume_skills=resume_skills or [],
                input_type=input_type,
                resume_text=resume_text,
                variation_seed=variation_seed,
            )
            if skill_question and skill_answer:
                return skill_question, skill_answer

        if strict_skill_mode:
            strict_blob = " ".join(
                [
                    source,
                    " ".join(str(item or "") for item in (key_requirements or [])),
                    str(role_title or ""),
                ]
            )
            derived_skills = self.extract_skill_hints_from_text(strict_blob)
            if not derived_skills:
                profile_skills = [
                    *[item for item in (required_skills or []) if self._is_skill_candidate(str(item or ""))],
                    *[item for item in (resume_skills or []) if self._is_skill_candidate(str(item or ""))],
                ]
                derived_skills = [str(item).strip() for item in profile_skills if str(item).strip()]
            if not derived_skills:
                derived_skills = self.infer_role_skill_defaults(role_title)
            if derived_skills:
                role_hint = self._resolve_role_title(role_title=role_title, context=source)
                skill = derived_skills[attempt_index % len(derived_skills)]
                question = self._build_skill_question(
                    skill=skill,
                    difficulty=difficulty,
                    tone="technical",
                    variant=attempt_index,
                    role_title=role_hint,
                    input_type=input_type,
                    requirement_focus="",
                )
                answer = self._build_skill_profile_answer(skill=skill, role_title=role_hint, requirement_focus="")
                validation_context = " ".join(
                    [
                        source,
                        " ".join(str(item or "") for item in derived_skills),
                        " ".join(str(item or "") for item in (required_skills or [])),
                        " ".join(str(item or "") for item in (resume_skills or [])),
                    ]
                )
                if self._is_valid_candidate(question, answer, validation_context, recent):
                    return question, answer
            raise RuntimeError("Could not derive any skill-focused question from this chunk")

        if self.model is not None:
            try:
                llm_question, llm_answer = self._llm_generate_with_model_fallback(
                    context=source,
                    difficulty=difficulty,
                    attempt_index=attempt_index,
                    recent_questions=recent,
                )
                return llm_question, llm_answer
            except Exception:
                pass

        return self._fallback_generate(source, recent)

    async def generate_question(
        self,
        *,
        context: str,
        difficulty: int,
        recent_questions: Sequence[str] | None = None,
        attempt_index: int = 0,
        require_llm: bool = False,
        role_title: str = "",
        required_skills: Sequence[str] | None = None,
        key_requirements: Sequence[str] | None = None,
        resume_skills: Sequence[str] | None = None,
        input_type: str = "jd",
        strict_skill_mode: bool = False,
        resume_text: str = "",
        variation_seed: str = "",
    ) -> tuple[str, str]:
        return await run_blocking(
            self._generate_question_sync,
            context=context,
            difficulty=difficulty,
            recent_questions=recent_questions,
            attempt_index=attempt_index,
            require_llm=require_llm,
            role_title=role_title,
            required_skills=required_skills,
            key_requirements=key_requirements,
            resume_skills=resume_skills,
            input_type=input_type,
            strict_skill_mode=strict_skill_mode,
            resume_text=resume_text,
            variation_seed=variation_seed,
        )

    async def generate_question_async(
        self,
        *,
        context: str,
        difficulty: int,
        recent_questions: Sequence[str] | None = None,
        attempt_index: int = 0,
        require_llm: bool = False,
        role_title: str = "",
        required_skills: Sequence[str] | None = None,
        key_requirements: Sequence[str] | None = None,
        resume_skills: Sequence[str] | None = None,
        input_type: str = "jd",
        strict_skill_mode: bool = False,
        resume_text: str = "",
        variation_seed: str = "",
    ) -> tuple[str, str]:
        return await self.generate_question(
            context=context,
            difficulty=difficulty,
            recent_questions=recent_questions,
            attempt_index=attempt_index,
            require_llm=require_llm,
            role_title=role_title,
            required_skills=required_skills,
            key_requirements=key_requirements,
            resume_skills=resume_skills,
            input_type=input_type,
            strict_skill_mode=strict_skill_mode,
            resume_text=resume_text,
            variation_seed=variation_seed,
        )

    def _is_production_ready_sync(
        self,
        *,
        question: str,
        answer: str,
        recent_questions: Sequence[str] | None = None,
    ) -> bool:
        recent = list(recent_questions or [])
        if not self._is_reasonable_question(question):
            return False
        if self._is_repeated_candidate(question, recent):
            return False
        if self._is_generic_question(question):
            return False
        if not self._is_answer_usable(answer):
            return False
        return True

    async def is_production_ready(
        self,
        *,
        question: str,
        answer: str,
        recent_questions: Sequence[str] | None = None,
    ) -> bool:
        return await run_blocking(
            self._is_production_ready_sync,
            question=question,
            answer=answer,
            recent_questions=recent_questions,
        )

    async def is_production_ready_async(
        self,
        *,
        question: str,
        answer: str,
        recent_questions: Sequence[str] | None = None,
    ) -> bool:
        return await self.is_production_ready(
            question=question,
            answer=answer,
            recent_questions=recent_questions,
        )

    def _llm_generate_with_model_fallback(
        self,
        *,
        context: str,
        difficulty: int,
        attempt_index: int,
        recent_questions: Sequence[str],
    ) -> tuple[str, str]:
        model_candidates = []
        if self.model is not None:
            model_candidates.append(self.model)
        for model_name in self._candidate_model_names():
            model = get_model(model_name)
            if model is not None:
                model_candidates.append(model)

        if not model_candidates:
            raise RuntimeError("LLM model is not configured for question generation.")

        last_error: Exception | None = None
        for model in model_candidates:
            try:
                question, answer = self._llm_generate(model, context=context, difficulty=difficulty, attempt_index=attempt_index)
                if self._is_valid_candidate(question, answer, context, recent_questions):
                    self.model = model
                    return question, answer
                last_error = RuntimeError("LLM generated an invalid question format. Please retry.")
            except Exception as exc:
                last_error = exc

        message = str(last_error or "Unknown LLM failure")
        if "resource_exhausted" in message.lower() or "quota" in message.lower() or "429" in message:
            raise RuntimeError("LLM quota exceeded for configured model(s). Update GEMINI_MODEL or billing/quota.")
        raise RuntimeError(f"LLM question generation failed: {message[:180]}")

    def _candidate_model_names(self) -> list[str]:
        return generation_model_names()

    def _llm_generate(self, model, *, context: str, difficulty: int, attempt_index: int) -> tuple[str, str]:
        difficulty_label = {1: "easy", 2: "medium", 3: "hard"}.get(difficulty, "easy")
        prompt = (
            "Generate one interview-style study question from the provided context. "
            "The question must be concise and answerable from the context only. "
            "Do not include headings, code, or answer labels in the question. "
            "Return STRICT JSON only in this schema: "
            '{"question":"...","answer":"..."}. '
            f"Difficulty: {difficulty_label}. Attempt index: {attempt_index}."
        )
        try:
            response = model.generate_content(
                f"{prompt}\n\nContext:\n{context}",
                generation_config={"temperature": 0.25, "response_mime_type": "application/json"},
                request_options={"timeout": 15},
            )
        except TypeError:
            response = model.generate_content(
                f"{prompt}\n\nContext:\n{context}",
                generation_config={"temperature": 0.25, "response_mime_type": "application/json"},
            )
        raw = extract_text(response) or "{}"

        question_raw = ""
        answer_raw = ""
        try:
            parsed = parse_json_response(raw)
            question_raw = str(parsed.get("question", ""))
            answer_raw = str(parsed.get("answer", ""))
        except Exception:
            question_match = re.search(r"(?im)^question\s*:\s*(.+)$", raw)
            answer_match = re.search(r"(?im)^answer\s*:\s*(.+)$", raw)
            question_raw = question_match.group(1) if question_match else ""
            answer_raw = answer_match.group(1) if answer_match else ""

        question = self._clean_focus_candidate(question_raw)
        answer = self._normalize_answer(answer_raw, context)

        if self._looks_like_command_prompt(question):
            question = self._command_prompt_to_question(question)
        elif question and not question.endswith("?"):
            question = f"{question.rstrip('.:!')}?"

        return question, answer

    def _fallback_generate(self, context: str, recent_questions: Sequence[str]) -> tuple[str, str]:
        for raw_question, raw_answer in self._extract_numbered_pairs(context):
            question = self._clean_focus_candidate(raw_question)
            if self._looks_like_command_prompt(question):
                question = self._command_prompt_to_question(question)
            answer = self._normalize_answer(raw_answer, context)
            if self._is_valid_candidate(question, answer, context, recent_questions):
                return question, answer

        for raw_question, raw_answer in self._extract_labeled_pairs(context):
            question = self._clean_focus_candidate(raw_question)
            if self._looks_like_command_prompt(question):
                question = self._command_prompt_to_question(question)
            answer = self._normalize_answer(raw_answer, context)
            if self._is_valid_candidate(question, answer, context, recent_questions):
                return question, answer

        answer_label = self._extract_answer_label_text(context)
        if answer_label:
            question = self._question_from_answer(answer_label)
            answer = self._normalize_answer(answer_label, context)
            if self._is_valid_candidate(question, answer, context, recent_questions):
                return question, answer

        concept, sentence = self._extract_concept_sentence(context)
        if concept and sentence:
            question = f"What is {concept}?"
            answer = self._normalize_answer(sentence, sentence)
            if self._is_valid_candidate(question, answer, context, recent_questions):
                return question, answer

        fallback_answer = self._normalize_answer(context, context)
        return "What is the main idea of this passage?", fallback_answer

    def _extract_numbered_pairs(self, context: str) -> list[tuple[str, str]]:
        pattern = re.compile(
            r"(?is)(?:^|\b)(?:q(?:uestion)?\s*)?(?P<num>\d{1,3})\s*[.):\-]\s*(?P<body>.+?)"
            r"(?=(?:\b(?:q(?:uestion)?\s*)?\d{1,3}\s*[.):\-])|$)"
        )
        matches = list(pattern.finditer(context))
        if not matches:
            return []

        pairs: list[tuple[str, str]] = []
        for match in matches:
            raw_question, raw_answer = self._split_numbered_block(match.group("body"))
            if not raw_question or not raw_answer:
                continue
            pairs.append((raw_question, raw_answer))

        return pairs

    def _split_numbered_block(self, block: str) -> tuple[str, str]:
        text = re.sub(r"\s+", " ", (block or "").strip())
        if not text:
            return "", ""

        q_match = re.match(r"(?is)(.+?\?)\s*(.*)$", text)
        if q_match:
            return q_match.group(1).strip(), q_match.group(2).strip()

        answer_label = re.search(r"(?is)\b(?:answer|ans|a)\s*[:\-]\s*", text)
        if answer_label:
            question = text[: answer_label.start()].strip()
            answer = text[answer_label.end() :].strip()
            question = question if question.endswith("?") else f"{question.rstrip('.:!')}?"
            return question, answer

        sentence_boundary = re.search(r"(?<=[a-z0-9])\s*[.:-]\s+", text, flags=re.IGNORECASE)
        if sentence_boundary:
            question = text[: sentence_boundary.start()].strip()
            answer = text[sentence_boundary.end() :].strip()
            if question and answer:
                question = question if question.endswith("?") else f"{question.rstrip('.:!')}?"
                return question, answer

        return self._infer_missing_qmark_pair(text)

    def _infer_missing_qmark_pair(self, text: str) -> tuple[str, str]:
        acronym_match = re.match(r"(?is)^what\s+is\s+([A-Z][A-Z0-9+/#\-]{1,12})\s+(.+)$", text)
        if acronym_match:
            subject = acronym_match.group(1).strip()
            answer = acronym_match.group(2).strip()
            return f"What is {subject}?", answer

        article_match = re.match(
            r"(?is)^what\s+is\s+([A-Za-z][A-Za-z0-9+/#\-]{1,30})\s+((?:a|an|the)\b.+)$",
            text,
        )
        if article_match:
            subject = article_match.group(1).strip()
            answer = article_match.group(2).strip()
            return f"What is {subject}?", answer

        stems = ("what is", "what are", "who is", "who are", "why is", "how does", "how do", "which is")
        cue_verbs = {
            "is",
            "are",
            "means",
            "refers",
            "describes",
            "includes",
            "organizes",
            "uses",
            "used",
            "allows",
            "helps",
            "enables",
            "provides",
            "works",
        }
        lowered = text.lower()
        for stem in stems:
            if not lowered.startswith(stem + " "):
                continue
            tail = text[len(stem) :].strip()
            parts = tail.split()
            if len(parts) < 3:
                continue
            cue_index = next((i for i, token in enumerate(parts[1:], start=1) if token.lower() in cue_verbs), -1)
            if cue_index == -1:
                continue
            subject = " ".join(parts[:cue_index]).strip(" -:.,")
            answer = " ".join(parts[cue_index:]).strip(" -:.,")
            if subject and answer:
                return f"{stem.capitalize()} {subject}?", answer

        return "", ""

    def _extract_labeled_pairs(self, context: str) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        answer_iter = list(re.finditer(r"(?i)\banswer\s*[:\-]\s*", context))
        for match in answer_iter:
            prefix = context[: match.start()]
            suffix = context[match.end() :]

            question = self._find_preceding_prompt(prefix)
            if not question:
                continue

            answer = self._extract_answer_span(suffix)
            if not answer:
                continue

            pairs.append((question, answer))
        return pairs

    def _find_preceding_prompt(self, prefix: str) -> str:
        window = prefix[-280:]
        pieces = [segment.strip() for segment in re.split(r"[\n\r]+", window) if segment.strip()]
        if not pieces:
            return ""

        candidate = pieces[-1]
        sentence_chunks = [part.strip() for part in re.split(r"(?<=[?.!])\s+", candidate) if part.strip()]
        if sentence_chunks:
            candidate = sentence_chunks[-1]

        candidate = re.sub(r"(?i)^\s*(?:q(?:uestion)?\s*\d*\s*[:.)\-]?\s*|q\s*:\s*|\d+[.)\-]?\s*)", "", candidate).strip()
        if not candidate:
            return ""
        return candidate

    def _extract_answer_span(self, suffix: str) -> str:
        if not suffix.strip():
            return ""

        stop = re.search(
            r"(?i)(?:\bnext question\b|\bquestion\s*\d+\s*[:.)\-]|\bq\s*\d+\s*[:.)\-]|\bq\s*:|\bexample\s*:|\bfollow up\b)",
            suffix,
        )
        candidate = suffix[: stop.start()] if stop else suffix
        first_line = candidate.splitlines()[0].strip()
        return first_line or candidate.strip()

    def _extract_answer_label_text(self, context: str) -> str:
        match = re.search(r"(?is)\banswer\s*[:\-]\s*(.+)$", context)
        if not match:
            return ""
        return self._extract_answer_span(match.group(1))

    def _extract_concept_sentence(self, context: str) -> tuple[str, str]:
        cleaned = re.sub(r"`[^`]*`", " ", context)
        cleaned = re.sub(r"\b\w+\([^)]*\)", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)

        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
        for sentence in sentences:
            if self._looks_code_like(sentence) or self._looks_like_heading(sentence):
                continue

            concept_match = re.search(
                r"\b(?:an|a|the)\s+([A-Za-z][A-Za-z0-9+/#' -]{2,80}?)\s+(?:where|that|which)\b",
                sentence,
                flags=re.IGNORECASE,
            )
            if concept_match:
                concept = self._clean_focus_candidate(concept_match.group(1))
                if self._is_clean_concept(concept):
                    return concept, sentence

            subject_match = re.search(
                r"\b([A-Za-z][A-Za-z0-9+/#' -]{1,80}?)\s+(?:is|are|means|refers to|describes|includes)\b",
                sentence,
                flags=re.IGNORECASE,
            )
            if subject_match:
                concept = self._clean_focus_candidate(subject_match.group(1))
                if self._is_clean_concept(concept):
                    return concept, sentence

        return "", ""

    def _question_from_answer(self, answer: str) -> str:
        answer = self._normalize_answer(answer, answer)
        subject_match = re.match(
            r"^\s*([A-Za-z][A-Za-z0-9+/#' -]{1,80}?)\s+(?:is|are|means|refers to|describes|includes)\b",
            answer,
            flags=re.IGNORECASE,
        )
        if subject_match:
            concept = self._clean_focus_candidate(subject_match.group(1))
            if self._is_clean_concept(concept):
                return f"What is {concept}?"

        concept, _sentence = self._extract_concept_sentence(answer)
        if concept:
            return f"What is {concept}?"

        return "What is the key concept in this answer?"

    def _is_reasonable_question(self, text: str) -> bool:
        question = text.strip()
        if not question.endswith("?"):
            return False
        if len(question) < 10:
            return False
        if len(question.split()) < 3:
            return False
        if self._looks_code_like(question):
            return False
        if self._looks_like_heading(question, allow_question_form=False):
            return False
        if self._has_multiple_question_heads(question):
            return False
        if not self._looks_like_interrogative_question(question):
            return False
        return True

    def _looks_like_heading(self, text: str, allow_question_form: bool = True) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if allow_question_form and stripped.endswith("?"):
            # If it's question-shaped, keep; otherwise treat heading with '?' as invalid.
            if self._looks_like_interrogative_question(stripped):
                return False
            return True
        if self._looks_like_command_prompt(stripped):
            return False
        if len(stripped.split()) < 3:
            return True
        if stripped.isupper():
            return True
        if re.match(r"^\d+[.)-]?\s", stripped):
            return True
        if re.search(r"\b(interview questions|contents|title)\b", stripped, flags=re.IGNORECASE):
            return True
        return False

    def _looks_like_interrogative_question(self, text: str) -> bool:
        stripped = text.strip()
        normalized = re.sub(r"[^a-z0-9\s]", " ", stripped.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return False

        first = normalized.split(" ", 1)[0]
        starters = {
            "what",
            "why",
            "how",
            "when",
            "where",
            "which",
            "who",
            "whom",
            "whose",
            "is",
            "are",
            "am",
            "was",
            "were",
            "do",
            "does",
            "did",
            "can",
            "could",
            "will",
            "would",
            "should",
            "has",
            "have",
            "had",
        }
        command_like = {"explain", "describe", "define", "compare", "differentiate", "list"}
        return first in starters or first in command_like

    def _is_valid_candidate(
        self,
        question: str,
        answer: str,
        context: str,
        recent_questions: Sequence[str],
    ) -> bool:
        if not question or not answer:
            return False
        if len(question) > 220:
            return False
        if self._is_repeated_candidate(question, recent_questions):
            return False
        if self._is_generic_question(question):
            return False
        if self._looks_garbled(question):
            return False
        if self._looks_like_heading(question, allow_question_form=False):
            return False
        if not self._looks_like_interrogative_question(question):
            return False
        if self._looks_like_answer_leakage(question):
            return False
        if not self._is_reasonable_question(question):
            return False
        if not self._is_answer_usable(answer):
            return False
        return self._has_grounding(question, answer, context)

    def _is_generic_question(self, question: str) -> bool:
        key = self._question_key(question)
        if key in self._GENERIC_QUESTION_KEYS:
            return True
        if key.startswith("what is the main idea of"):
            return True
        return False

    def _is_answer_usable(self, answer: str) -> bool:
        cleaned = re.sub(r"\s+", " ", (answer or "").strip())
        if not cleaned:
            return False
        if len(cleaned.split()) < 3:
            return False
        if len(cleaned) > 260:
            return False
        if self._looks_code_like(cleaned) and len(cleaned) > 120:
            return False
        # Reject answers that clearly concatenate multiple numbered items.
        if len(re.findall(r"\b\d{1,2}\s*[.)]", cleaned)) >= 3:
            return False
        return True

    def _looks_like_answer_leakage(self, question: str) -> bool:
        normalized = self._question_key(question)
        return bool(
            re.match(r"^(?:what|which|who|when|where|why|how)\s+(?:is|are)\s+(?:the\s+)?answer\b", normalized)
            or normalized.startswith("answer ")
            or normalized.startswith("ans ")
        )

    def _is_repeated_candidate(self, question: str, recent_questions: Sequence[str]) -> bool:
        candidate_key = self._question_key(question)
        if not candidate_key:
            return False

        candidate_keywords = self._keywords(question)
        for item in recent_questions:
            if not item:
                continue
            recent_key = self._question_key(item)
            if candidate_key == recent_key:
                return True

            recent_keywords = self._keywords(item)
            if not candidate_keywords or not recent_keywords:
                continue

            overlap = len(candidate_keywords.intersection(recent_keywords))
            if overlap < 3:
                continue

            union = len(candidate_keywords.union(recent_keywords))
            jaccard = overlap / max(1, union)
            coverage = max(
                overlap / max(1, len(candidate_keywords)),
                overlap / max(1, len(recent_keywords)),
            )

            if jaccard >= 0.45 or (overlap >= 4 and coverage >= 0.6):
                return True

        return False

    def _question_key(self, question: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", question.lower())).strip()

    def _has_grounding(self, question: str, answer: str, context: str) -> bool:
        context_keywords = self._keywords(context)
        if not context_keywords:
            return True

        question_keywords = self._keywords(question)
        answer_keywords = self._keywords(answer)
        question_overlap = question_keywords.intersection(context_keywords)
        answer_overlap = answer_keywords.intersection(context_keywords)
        if len(answer_overlap) >= 2:
            return True
        if len(answer_overlap) >= 1 and len(question_overlap) >= 1:
            return True
        if len(question_overlap) >= 2:
            return True
        return False

    def _normalize_answer(self, raw_answer: str, fallback: str) -> str:
        answer = re.sub(r"\s+", " ", (raw_answer or "").strip()).strip(" -:")
        answer = re.sub(r"(?i)^(?:answer|ans|a)\b\s*[:\-]?\s*", "", answer).strip()
        answer = re.sub(r"(?i)^example\s*[:\-]\s*", "", answer).strip()
        answer = re.split(r"(?i)\b(?:next question|question\s*\d*|q\s*\d*)\s*[:.)\-]", answer, maxsplit=1)[0].strip()
        answer = re.sub(r"[ï¿½]+", " ", answer)
        answer = re.sub(r"\s+", " ", answer).strip()
        if len(answer) > 260:
            answer = answer[:260].rstrip()
        if answer and not self._looks_code_like(answer):
            return answer
        fallback_text = re.sub(r"\s+", " ", (fallback or "").strip()).strip(" -:")
        return fallback_text or "Refer to the document section for the answer."

    def _clean_focus_candidate(self, text: str) -> str:
        original = re.sub(r"\s+", " ", (text or "").strip())
        had_question_mark = "?" in original

        cleaned = original.strip(" -:")
        cleaned = re.sub(r"(?i)^(?:answer|ans|a)\b\s*[:\-]?\s*", "", cleaned).strip()
        cleaned = re.sub(r"(?i)^(?:next question|question)\s*:\s*", "", cleaned).strip()
        cleaned = re.sub(r"^(?:[Qq](?:uestion)?\s*\d*|\d+)\s*[.):-]?\s*", "", cleaned).strip()
        cleaned = re.sub(
            r"(?i)\s*(?:based on|from|as per|according to)\s+(?:the\s+)?(?:provided|given|above)\s+(?:example|examples)\s*[?.!]*\s*$",
            "",
            cleaned,
        ).strip(" -:")
        if had_question_mark and cleaned and not cleaned.endswith("?"):
            cleaned = f"{cleaned.rstrip('.:!')}?"
        return cleaned

    def _is_clean_concept(self, value: str) -> bool:
        stripped = value.strip()
        if not stripped:
            return False
        if len(stripped.split()) > 6:
            return False
        if re.search(r"[_(){}[\]<>=\"`]", stripped):
            return False
        if re.search(r"\b(?:db|query|search|import|class|def|return)\b", stripped, flags=re.IGNORECASE):
            return False
        words = re.findall(r"[A-Za-z][A-Za-z'-]*", stripped)
        if not words:
            return False
        lowered = {word.lower() for word in words}
        return not lowered.issubset(self._CONCEPT_NOISE)

    def _command_prompt_to_question(self, prompt: str) -> str:
        cleaned = prompt.strip().rstrip(".:?")
        lowered = cleaned.lower()
        if lowered.startswith("find "):
            return f"How would you {lowered}?"
        if lowered.startswith("swap "):
            return f"How would you {lowered}?"
        if lowered.startswith("write "):
            return f"What does the document ask you to write about {cleaned[6:].strip()}?"
        if lowered.startswith("define "):
            return f"What is {cleaned[7:].strip()}?"
        if lowered.startswith("explain "):
            return f"Can you explain {cleaned[8:].strip()}?"
        return f"How would you {lowered}?"

    def _skill_focused_generate(
        self,
        *,
        context: str,
        difficulty: int,
        recent_questions: Sequence[str],
        attempt_index: int,
        role_title: str,
        required_skills: Sequence[str],
        key_requirements: Sequence[str],
        resume_skills: Sequence[str],
        input_type: str,
        resume_text: str,
        variation_seed: str,
    ) -> tuple[str, str]:
        focus_skills = self._resolve_focus_skills(
            context=context,
            required_skills=required_skills,
            key_requirements=key_requirements,
            resume_skills=resume_skills,
            resume_text=resume_text,
            input_type=input_type,
        )
        if not focus_skills:
            return "", ""

        role_hint = self._resolve_role_title(role_title=role_title, context=context)
        is_technical = self._is_technical_role(role_title=role_hint, focus_skills=focus_skills)
        tone = "technical" if is_technical else "behavioral"

        seed_base = f"{variation_seed}|{attempt_index}|{difficulty}|{role_hint}|{'|'.join(focus_skills)}"
        variant_index = int(hashlib.sha256(seed_base.encode("utf-8")).hexdigest(), 16)
        clean_requirements = [
            re.sub(r"\s+", " ", str(item or "").strip())
            for item in key_requirements
            if str(item or "").strip()
        ]
        validation_context = " ".join([context, " ".join(focus_skills), " ".join(clean_requirements)]).strip()

        for offset in range(min(8, len(focus_skills) * 2)):
            focus = focus_skills[(variant_index + offset) % len(focus_skills)]
            canonical_skill = self._canonical_skill_key(focus)
            requirement_focus = clean_requirements[(variant_index + offset) % len(clean_requirements)] if clean_requirements else ""
            normalized_input_type = "resume" if str(input_type or "").strip().lower() == "resume" else "jd"

            question = ""
            answer = ""
            curriculum_pair = None
            if normalized_input_type == "jd":
                curriculum_pair = self._skill_curriculum_pair(
                    canonical_skill=canonical_skill,
                    difficulty=difficulty,
                    variant=(attempt_index + offset),
                )
            if curriculum_pair:
                question, answer = curriculum_pair
            else:
                question = self._build_skill_question(
                    skill=focus,
                    difficulty=difficulty,
                    tone=tone,
                    variant=(variant_index + offset),
                    role_title=role_hint,
                    input_type=input_type,
                    requirement_focus=self._sanitize_requirement_focus(requirement_focus),
                )
                answer = self._build_skill_answer(skill=focus, context=context)

            if not answer:
                answer = self._build_skill_profile_answer(
                    skill=focus,
                    role_title=role_hint,
                    requirement_focus=requirement_focus,
                )

            if not self.text_mentions_focus_skill(question, focus_skills):
                continue
            if self._contains_non_skill_noise(question):
                continue
            if not answer:
                continue
            if not self._is_valid_candidate(question, answer, validation_context or context, recent_questions):
                continue
            return question, answer

        return "", ""

    def _canonical_skill_key(self, value: str) -> str:
        normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+/#\s-]", " ", str(value or "").lower())).strip(" -")
        if not normalized:
            return ""

        for skill_key, pattern in self._SKILL_PATTERN_MAP.items():
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return skill_key
        return normalized

    def _skill_curriculum_pair(self, *, canonical_skill: str, difficulty: int, variant: int) -> tuple[str, str] | None:
        curriculum = self._SKILL_CURRICULUM.get(canonical_skill)
        if not curriculum:
            return None

        pool: list[tuple[str, str]] = list(curriculum.get(1, []))
        if difficulty >= 2:
            pool.extend(curriculum.get(2, []))
        if difficulty >= 3:
            pool.extend(curriculum.get(3, []))
        if not pool:
            return None

        return pool[variant % len(pool)]

    def _sanitize_requirement_focus(self, requirement_focus: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(requirement_focus or "").strip())
        if not cleaned:
            return ""

        lowered = cleaned.lower()
        noisy_tokens = {
            "bond",
            "deposit",
            "salary",
            "ctc",
            "lpa",
            "stipend",
            "notice period",
            "working days",
            "shift",
            "marks",
            "percentage",
            "cgpa",
            "board exam",
            "graduation",
            "batch",
            "male candidates",
            "female candidates",
            "eligibility",
        }
        if any(token in lowered for token in noisy_tokens):
            return ""
        if re.search(r"\b\d+\b", lowered) and re.search(r"\b(?:month|year|lakh|rupee|rs|inr|%|percent|percentage)\b", lowered):
            return ""
        if len(cleaned.split()) > 10:
            return ""
        return cleaned

    def _resolve_focus_skills(
        self,
        *,
        context: str,
        required_skills: Sequence[str],
        key_requirements: Sequence[str],
        resume_skills: Sequence[str],
        resume_text: str,
        input_type: str,
    ) -> list[str]:
        candidates: list[str] = []
        required_clean: list[str] = []
        resume_clean: list[str] = []

        def _append_unique(bucket: list[str], value: str) -> None:
            cleaned = re.sub(r"\s+", " ", str(value or "").strip())
            if not cleaned:
                return
            if cleaned.lower() in {item.lower() for item in bucket}:
                return
            bucket.append(cleaned)

        for skill in required_skills:
            _append_unique(required_clean, skill)

        for skill in resume_skills:
            _append_unique(resume_clean, skill)

        if not resume_clean and resume_text.strip():
            for skill, pattern in self._SKILL_PATTERN_MAP.items():
                if re.search(pattern, resume_text, flags=re.IGNORECASE):
                    _append_unique(resume_clean, skill)

        req_key_map: dict[str, str] = {}
        for skill in required_clean:
            key = self._canonical_skill_key(skill)
            if key and key not in req_key_map:
                req_key_map[key] = skill

        resume_keys = {
            self._canonical_skill_key(skill)
            for skill in resume_clean
            if self._canonical_skill_key(skill)
        }

        overlap: list[str] = []
        for key, skill in req_key_map.items():
            if key in resume_keys:
                _append_unique(overlap, skill)

        jd_only: list[str] = []
        overlap_keys = {self._canonical_skill_key(item) for item in overlap}
        for skill in required_clean:
            if self._canonical_skill_key(skill) not in overlap_keys:
                _append_unique(jd_only, skill)

        resume_only: list[str] = []
        taken_keys = {
            self._canonical_skill_key(item)
            for item in [*overlap, *jd_only]
        }
        for skill in resume_clean:
            if self._canonical_skill_key(skill) not in taken_keys:
                _append_unique(resume_only, skill)

        normalized_input_type = "resume" if str(input_type or "").strip().lower() == "resume" else "jd"
        priority_buckets: list[list[str]]
        if normalized_input_type == "resume":
            priority_buckets = [overlap, resume_only, jd_only]
        else:
            # In JD mode, avoid resume-only detours when JD-required signals exist.
            priority_buckets = [overlap, jd_only]
            if not overlap and not jd_only:
                priority_buckets.append(resume_only)

        for bucket in priority_buckets:
            for skill in bucket:
                if self._is_skill_candidate(skill):
                    _append_unique(candidates, skill)

        if not candidates:
            for req in key_requirements:
                req_text = re.sub(r"\s+", " ", str(req or "").strip())
                if not req_text:
                    continue
                parts = [part.strip(" .") for part in re.split(r",|/|\band\b", req_text, flags=re.IGNORECASE)]
                for part in parts:
                    if not part:
                        continue
                    words = part.split()
                    if len(words) > 7:
                        continue
                    if len(" ".join(words)) < 4:
                        continue
                    normalized = " ".join(words)
                    if not self._is_skill_candidate(normalized):
                        continue
                    if normalized.lower() not in {item.lower() for item in candidates}:
                        candidates.append(normalized)

        jd_blob = " ".join([context, " ".join(key_requirements)]).lower()
        resume_blob = str(resume_text or "").lower()
        if normalized_input_type == "resume":
            lower_blob = " ".join([jd_blob, resume_blob]).strip()
        else:
            # In JD mode, only expand with resume text when we still have no viable JD focus skills.
            lower_blob = jd_blob if candidates else " ".join([jd_blob, resume_blob]).strip()
        for skill, pattern in self._SKILL_PATTERN_MAP.items():
            if re.search(pattern, lower_blob, flags=re.IGNORECASE):
                if skill.lower() not in {item.lower() for item in candidates}:
                    candidates.append(skill)

        if not candidates:
            return []

        # Sort by apparent frequency in context blob to prioritize JD-relevant skills.
        scored = []
        for index, skill in enumerate(candidates):
            count = len(re.findall(re.escape(skill.lower()), lower_blob))
            scored.append((count, index, skill))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored[:12]]

    def _build_skill_profile_answer(self, *, skill: str, role_title: str, requirement_focus: str) -> str:
        role = self._sanitize_role_label(role_title)
        clean_skill = re.sub(r"\s+", " ", (skill or "the skill").strip()) or "the skill"
        focus = self._sanitize_requirement_focus(requirement_focus)
        if focus:
            return (
                f"For {role}, {clean_skill} should be explained with one practical example that directly addresses: {focus}."
            )
        return f"For {role}, explain {clean_skill} with a clear concept summary and one practical project-level example."

    def _is_skill_candidate(self, value: str) -> bool:
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        if not cleaned:
            return False

        lowered = cleaned.lower()
        if any(token in lowered for token in self._NON_SKILL_NOISE_TOKENS):
            return False
        if re.search(r"\b\d+\s*(?:%|percent|percentage|month|months|year|years|lakh|lakhs|rs|inr)\b", lowered):
            return False
        if len(cleaned.split()) > 6:
            return False
        return True

    def _contains_non_skill_noise(self, text: str) -> bool:
        lowered = str(text or "").lower()
        return any(token in lowered for token in self._NON_SKILL_NOISE_TOKENS)

    def contains_non_skill_noise(self, text: str) -> bool:
        return self._contains_non_skill_noise(text)

    def extract_skill_hints_from_text(self, text: str, *, max_items: int = 12) -> list[str]:
        blob = str(text or "")
        hints: list[str] = []
        seen: set[str] = set()

        def _append_hint(value: str) -> None:
            cleaned = re.sub(r"\s+", " ", str(value or "").strip(" ,;:-"))
            if not cleaned:
                return
            if not self._is_skill_candidate(cleaned):
                return
            key = cleaned.lower()
            if key in seen:
                return
            seen.add(key)
            hints.append(cleaned)

        for skill, pattern in self._SKILL_PATTERN_MAP.items():
            if not re.search(pattern, blob, flags=re.IGNORECASE):
                continue
            if not self._is_skill_candidate(skill):
                continue
            _append_hint(skill)
            if len(hints) >= max_items:
                break

        list_patterns = [
            r"(?i)(?:required\s+skills?|technical\s+skills?|skills?|technologies|tools|proficiency\s+in|knowledge\s+of)\s*[:\-]\s*([^\n.]{4,220})",
            r"(?i)(?:must\s+have|good\s+understanding\s+of|hands[-\s]?on\s+in)\s+([^\n.]{4,220})",
        ]
        for pattern in list_patterns:
            for match in re.finditer(pattern, blob):
                segment = match.group(1)
                for token in re.split(r",|/|\||\band\b|\bor\b", segment, flags=re.IGNORECASE):
                    candidate = re.sub(r"\s+", " ", str(token or "").strip(" ,;:-"))
                    if not candidate:
                        continue
                    if len(candidate.split()) > 4:
                        continue
                    if re.search(r"\b(?:minimum|max|at least|throughout|eligible)\b", candidate, flags=re.IGNORECASE):
                        continue
                    _append_hint(candidate)
                    if len(hints) >= max_items:
                        return hints[:max_items]

        return hints

    def infer_role_skill_defaults(self, role_title: str, *, max_items: int = 6) -> list[str]:
        lowered = re.sub(r"\s+", " ", str(role_title or "").lower()).strip()
        defaults: list[str] = []
        for role_token, skills in self._ROLE_SKILL_DEFAULTS.items():
            if role_token in lowered:
                defaults.extend(skills)

        if not defaults:
            if not lowered:
                return []
            defaults = ["Problem Solving", "Communication"]

        deduped: list[str] = []
        seen: set[str] = set()
        for item in defaults:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            if self._is_skill_candidate(item):
                deduped.append(item)
            if len(deduped) >= max_items:
                break
        return deduped

    def _is_technical_role(self, *, role_title: str, focus_skills: Sequence[str]) -> bool:
        role_lower = (role_title or "").lower()
        skill_blob = " ".join(focus_skills).lower()
        technical_hits = sum(1 for token in self._TECHNICAL_ROLE_HINTS if token in role_lower)
        technical_hits += sum(1 for token in self._TECHNICAL_SKILL_HINTS if token in skill_blob)
        non_technical_hits = sum(1 for token in self._NON_TECHNICAL_ROLE_HINTS if token in role_lower)
        non_technical_hits += sum(1 for token in self._NONTECHNICAL_SKILL_HINTS if token in skill_blob)

        if technical_hits == 0 and non_technical_hits == 0:
            return False
        return technical_hits > non_technical_hits

    def _build_skill_question(
        self,
        *,
        skill: str,
        difficulty: int,
        tone: str,
        variant: int,
        role_title: str,
        input_type: str,
        requirement_focus: str,
    ) -> str:
        skill_clean = re.sub(r"\s+", " ", skill.strip())
        role_label = self._sanitize_role_label(role_title)

        normalized_input_type = "resume" if str(input_type or "").strip().lower() == "resume" else "jd"
        req = re.sub(r"\s+", " ", requirement_focus.strip()) if requirement_focus else ""
        req_suffix = f" while handling {req.lower()}" if req else ""

        if normalized_input_type == "resume":
            if difficulty <= 1:
                templates = [
                    f"In your resume for {role_label}, where did you use {skill_clean} in a real project",
                    f"In your experience as {role_label}, what was your main responsibility when using {skill_clean}",
                    f"Can you explain one real task from your resume where you applied {skill_clean} as {role_label}",
                ]
            elif difficulty == 2:
                templates = [
                    f"As {role_label}, describe a project decision you made while using {skill_clean} and why you made it",
                    f"As {role_label}, what challenge did you face while using {skill_clean}, and how did you solve it",
                    f"How did you, as {role_label}, validate that your implementation with {skill_clean} was correct",
                ]
            else:
                templates = [
                    f"As {role_label}, what is the toughest production-like issue you handled using {skill_clean}, and what trade-off did you make",
                    f"How would you, as {role_label}, redesign your previous {skill_clean} implementation for better scale or reliability",
                    f"In a complex scenario for {role_label}, how would you debug and optimize a {skill_clean}-based feature end to end",
                ]
        else:
            if difficulty <= 1:
                templates = [
                    f"Why is {skill_clean} important for {role_label}{req_suffix}",
                    f"What core concepts should a {role_label} beginner know in {skill_clean}{req_suffix}",
                    f"How is {skill_clean} commonly used in real projects for {role_label}{req_suffix}",
                ]
            elif difficulty == 2:
                templates = [
                    f"How would you apply {skill_clean} to implement a practical feature for {role_label}{req_suffix}",
                    f"What best practices would you follow as {role_label} while building with {skill_clean}{req_suffix}",
                    f"How would you, as {role_label}, test and validate a feature built using {skill_clean}{req_suffix}",
                ]
            else:
                templates = [
                    f"What trade-offs do you consider as {role_label} when designing a complex solution with {skill_clean}{req_suffix}",
                    f"How would you, as {role_label}, troubleshoot and optimize a failing {skill_clean}-based workflow{req_suffix}",
                    f"How would you architect a scalable and maintainable module using {skill_clean} for {role_label}{req_suffix}",
                ]

        question = templates[variant % len(templates)]
        if not question.endswith("?"):
            question = f"{question.rstrip('.:!')}?"
        return question

    def _resolve_role_title(self, *, role_title: str, context: str) -> str:
        if (role_title or "").strip():
            return self._sanitize_role_label(role_title)

        lines = [line.strip() for line in re.split(r"[\n\r]+", context or "") if line.strip()]
        for line in lines[:10]:
            match = re.search(r"(?i)\b(?:role|position|title)\s*[:\-]\s*([A-Za-z][A-Za-z0-9&/()\- ,]{3,80})", line)
            if match:
                return self._sanitize_role_label(match.group(1).strip(" ."))

        for line in lines[:10]:
            lowered = line.lower()
            if any(token in lowered for token in ("engineer", "manager", "specialist", "associate", "executive", "analyst", "coordinator", "consultant")):
                if 2 <= len(line.split()) <= 10:
                    return self._sanitize_role_label(line.strip(" ."))

        return "this role"

    def _sanitize_role_label(self, role_title: str) -> str:
        cleaned = str(role_title or "")
        cleaned = re.sub(r"\s*\([^)]*\)", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
        return cleaned or "this role"

    def _build_skill_answer(self, *, skill: str, context: str) -> str:
        lines = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", context) if segment.strip()]
        skill_lower = skill.lower()

        for line in lines:
            lowered = line.lower()
            if skill_lower in lowered and len(line.split()) >= 5 and len(line) <= 260:
                return self._normalize_answer(line, context)

        pattern = self._SKILL_PATTERN_MAP.get(skill_lower)
        if pattern:
            for line in lines:
                if re.search(pattern, line, flags=re.IGNORECASE) and len(line.split()) >= 5 and len(line) <= 260:
                    return self._normalize_answer(line, context)

        return ""

    def text_mentions_focus_skill(self, text: str, focus_skills: Sequence[str] | None = None) -> bool:
        clean_text = str(text or "").strip().lower()
        skills = [str(item or "").strip() for item in (focus_skills or []) if str(item or "").strip()]
        if not skills:
            return True
        if not clean_text:
            return False

        for raw_skill in skills:
            skill_key = self._canonical_skill_key(raw_skill)
            if not skill_key:
                continue
            pattern = self._SKILL_PATTERN_MAP.get(skill_key)
            if pattern and re.search(pattern, clean_text, flags=re.IGNORECASE):
                return True

            escaped = re.escape(skill_key)
            if re.search(rf"\b{escaped}\b", clean_text, flags=re.IGNORECASE):
                return True

        return False

    def _keywords(self, text: str) -> set[str]:
        keywords = set()
        for token in re.findall(r"[A-Za-z][A-Za-z'-]*", text.lower()):
            normalized = token.strip("' -")
            if len(normalized) < 4 or normalized in self._STOP_WORDS:
                continue
            keywords.add(normalized)
        return keywords

    def _looks_code_like(self, text: str) -> bool:
        return bool(
            re.search(r"[`{}();]|=>|::|\b(?:import|class|def|return|function|const|let|var)\b", text)
            or ".similarity_search(" in text
            or re.search(r"\b\w+\([^)]*\)", text)
        )

    def _looks_like_command_prompt(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped or stripped.endswith("?"):
            return False
        return bool(re.match(r"(?i)^(?:find|define|describe|explain|list|name|identify|write|compare|differentiate)\b", stripped))

    def _has_multiple_question_heads(self, question: str) -> bool:
        tokens = re.findall(r"\b(?:what|why|how|when|where|which|who|is|are|can|should|do|does|did)\b", question.lower())
        return len(tokens) > 2

    def _looks_garbled(self, question: str) -> bool:
        if len(question) < 8:
            return True
        alpha = len(re.findall(r"[A-Za-z]", question))
        if alpha < max(4, len(question) // 4):
            return True

        lowered = question.lower().strip()
        if "until yo" in lowered:
            return True
        if re.search(r"\b(?:until|with|from|for|about|to|in)\s+[a-z]{1,2}\?$", lowered):
            return True

        return False


question_engine = QuestionEngine()

