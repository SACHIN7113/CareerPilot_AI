import re
from typing import Any

from app.core.async_utils import run_blocking
from app.services.gemini_service import (
    _extract_text_sync as extract_text,
    _get_model_sync as get_model,
    _parse_json_response_sync as parse_json_response,
)


_SKILL_PATTERNS = {
    "Python": r"\bpython\b",
    "Java": r"\bjava\b",
    "JavaScript": r"\bjavascript\b|\bjs\b",
    "TypeScript": r"\btypescript\b|\bts\b",
    "HTML": r"\bhtml\b",
    "CSS": r"\bcss\b",
    "React": r"\breact\b",
    "Node.js": r"\bnode(?:\.js)?\b",
    "FastAPI": r"\bfastapi\b",
    "Django": r"\bdjango\b",
    "Flask": r"\bflask\b",
    "SQL": r"\bsql\b|\bmysql\b|\bpostgres(?:ql)?\b|\bsqlite\b",
    "MongoDB": r"\bmongodb\b",
    "Docker": r"\bdocker\b",
    "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "AWS": r"\baws\b",
    "Azure": r"\bazure\b",
    "GCP": r"\bgcp\b|\bgoogle cloud\b",
    "REST API": r"\brest\b|\bapi\b",
    "Testing": r"\btesting\b|\bqa\b|\bselenium\b|\bpostman\b",
    "Git": r"\bgit\b|\bgithub\b|\bgitlab\b",
    "Communication": r"\bcommunication\b|\binterpersonal\b",
    "Problem Solving": r"\bproblem\s*solv(?:ing|e)\b",
}

_COMPANY_PLACEHOLDER = "the company"
_ROLE_PLACEHOLDER = "this role"

_COMPANY_REJECT_TOKENS = {
    "our team",
    "join our team",
    "if you think",
    "job description",
    "campus drive",
    "great opportunity",
    "apply now",
    "hiring now",
    "we are",
    "you are",
    "batch",
    "freshers",
    "students",
}

_ROLE_REJECT_TOKENS = {
    "if you think",
    "great opportunity",
    "job description",
    "we are",
    "you are",
    "fresher",
    "freshers",
    "enthusiastic",
    "curious",
    "batch",
    "students",
}

_ROLE_KEYWORDS = {
    "engineer",
    "developer",
    "analyst",
    "intern",
    "manager",
    "specialist",
    "support",
    "architect",
    "consultant",
    "administrator",
    "tester",
    "qa",
    "scientist",
    "designer",
    "lead",
    "officer",
    "executive",
    "associate",
    "sde",
    "owner",
    "director",
    "trainee",
    "coordinator",
}

_SALARY_TOKENS = ("ctc", "lpa", "per annum", "per year", "salary")


def _build_jd_overview_sync(text: str, filename: str = "") -> dict[str, Any]:
    normalized_text = re.sub(r"\s+", " ", (text or "").strip())[:20000]
    lower_text = normalized_text.lower()

    extracted_company = _extract_company_name(normalized_text, filename)
    extracted_role = _extract_role_title(normalized_text, filename)
    company_name = _coerce_company_candidate(extracted_company)
    role_title = _coerce_role_candidate(extracted_role)
    required_skills = _extract_required_skills(lower_text)
    key_requirements = _extract_key_requirements(text)

    if not key_requirements:
        key_requirements = [
            "Review the JD carefully for role responsibilities and mandatory skills.",
            "Prepare examples from projects or internships for each required skill.",
        ]

    fallback = _build_fallback_payload(company_name, role_title, required_skills, key_requirements)

    llm_overview = _build_jd_overview_with_llm(normalized_text)
    if not llm_overview:
        return fallback

    llm_company = _coerce_company_candidate(llm_overview.get("company_name") or "")
    llm_role = _coerce_role_candidate(llm_overview.get("role_title") or "")

    company_name = _pick_identity_value(primary=company_name, secondary=llm_company, placeholder=_COMPANY_PLACEHOLDER)
    role_title = _pick_identity_value(primary=role_title, secondary=llm_role, placeholder=_ROLE_PLACEHOLDER)

    resolved_fallback = _build_fallback_payload(company_name, role_title, required_skills, key_requirements)

    return {
        "company_name": company_name,
        "role_title": role_title,
        "overview": _clean_phrase(llm_overview.get("overview") or resolved_fallback["overview"], max_len=360),
        "required_skills": _clean_list(llm_overview.get("required_skills"), max_items=12, max_len=40)
        or resolved_fallback["required_skills"],
        "key_requirements": _clean_list(llm_overview.get("key_requirements"), max_items=6, max_len=170)
        or resolved_fallback["key_requirements"],
        "what_to_prepare": _clean_list(llm_overview.get("what_to_prepare"), max_items=5, max_len=170)
        or resolved_fallback["what_to_prepare"],
        "generated_by": "llm",
    }


async def build_jd_overview(text: str, filename: str = "") -> dict[str, Any]:
    return await run_blocking(_build_jd_overview_sync, text, filename)


async def build_jd_overview_async(text: str, filename: str = "") -> dict[str, Any]:
    return await build_jd_overview(text, filename)


def _extract_jd_identity_sync(text: str, filename: str = "") -> dict[str, str]:
    normalized_text = re.sub(r"\s+", " ", (text or "").strip())[:20000]

    extracted_company = _extract_company_name(normalized_text, filename)
    extracted_role = _extract_role_title(normalized_text, filename)
    company_name = _coerce_company_candidate(extracted_company)
    role_title = _coerce_role_candidate(extracted_role)

    needs_llm_help = company_name == _COMPANY_PLACEHOLDER or role_title == _ROLE_PLACEHOLDER
    if needs_llm_help:
        llm_overview = _build_jd_overview_with_llm(normalized_text)
        llm_company = _coerce_company_candidate((llm_overview or {}).get("company_name") or "")
        llm_role = _coerce_role_candidate((llm_overview or {}).get("role_title") or "")
        company_name = _pick_identity_value(primary=company_name, secondary=llm_company, placeholder=_COMPANY_PLACEHOLDER)
        role_title = _pick_identity_value(primary=role_title, secondary=llm_role, placeholder=_ROLE_PLACEHOLDER)

    return {
        "company_name": company_name,
        "role_title": role_title,
    }


async def extract_jd_identity(text: str, filename: str = "") -> dict[str, str]:
    return await run_blocking(_extract_jd_identity_sync, text, filename)


def _build_jd_overview_with_llm(normalized_text: str) -> dict[str, Any] | None:
    model = get_model()
    if model is None:
        return None

    prompt = (
        "Analyze this company job description and return a student-friendly summary in strict JSON. "
        "Return only JSON with keys: company_name, role_title, overview, required_skills, key_requirements, what_to_prepare. "
        "Requirements: overview should be simple and accurate in 2-3 sentences, required_skills max 12 items, "
        "key_requirements max 6 bullet points, what_to_prepare max 5 practical tips."
    )

    try:
        response = model.generate_content(
            f"{prompt}\n\nJD:\n{normalized_text[:9000]}",
            generation_config={"temperature": 0.15, "response_mime_type": "application/json"},
        )
        parsed = parse_json_response(extract_text(response) or "{}")
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None

    return None


def _extract_company_name(text: str, filename: str) -> str:
    patterns = (
        r"(?:about\s+company|company\s+name|organization)\s*[:\-]\s*([A-Za-z0-9&.,'\- ]{3,80})",
        r"\b([A-Z][A-Za-z0-9&.,'()\- ]{2,60})\s+is\s+(?:looking\s+for|hiring|seeking)\b",
        r"join\s+([A-Z][A-Za-z0-9&.,'\- ]{2,60})\s+(?:as|for|in)",
        r"at\s+([A-Z][A-Za-z0-9&.,'\- ]{2,60})\s+(?:as|for|in)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = _clean_phrase(match.group(1), max_len=60)
            if not _is_valid_company_candidate(candidate):
                continue
            return candidate

    if filename:
        base = re.sub(r"\.(pdf|docx|txt)$", "", filename, flags=re.IGNORECASE)
        base = re.sub(r"[_\-]", " ", base)
        token_match = re.search(r"([A-Za-z][A-Za-z ]{2,40})(?:campus|drive|jd|job)", base, flags=re.IGNORECASE)
        if token_match:
            filename_candidate = _clean_phrase(token_match.group(1), max_len=60)
            if _is_valid_company_candidate(filename_candidate):
                return filename_candidate

    return _COMPANY_PLACEHOLDER


def _extract_role_title(text: str, filename: str) -> str:
    patterns = (
        r"(?:role|position|job\s*title|hiring\s*for)\s*[:\-]?\s*([A-Za-z][A-Za-z0-9/\- ,]{3,80})",
        r"\bfor\s+(?:the\s+)?([A-Za-z][A-Za-z0-9/&()\- ,]{3,80})\s+role\b",
        r"\b(?:hiring|looking\s+for|seeking)\s+(?:for\s+)?(?:an?\s+)?([A-Za-z][A-Za-z0-9/&()\- ,]{3,80})",
        r"(?:looking\s+for|seeking)\s+(?:an?\s+)?([A-Za-z][A-Za-z0-9/\- ,]{3,70})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = _clean_phrase(match.group(1), max_len=70)
            candidate = re.split(r"\b(with|who|to|for|at|in)\b", candidate, maxsplit=1)[0].strip(" ,;:-")
            if _is_valid_role_candidate(candidate):
                return candidate

    lower_filename = filename.lower()
    if "software" in lower_filename:
        return "Software role"
    if "support" in lower_filename:
        return "Support role"

    return _ROLE_PLACEHOLDER


def _extract_required_skills(lower_text: str) -> list[str]:
    found: list[str] = []
    for skill, pattern in _SKILL_PATTERNS.items():
        if re.search(pattern, lower_text):
            found.append(skill)
        if len(found) >= 12:
            break
    return found


def _extract_key_requirements(raw_text: str) -> list[str]:
    lines = [line.strip(" -\t") for line in re.split(r"\r?\n", raw_text or "") if line.strip()]
    picked: list[str] = []
    keywords = (
        "required",
        "must",
        "responsibil",
        "qualification",
        "experience",
        "skills",
        "knowledge",
        "ability",
        "eligible",
    )

    for line in lines:
        lowered = line.lower()
        if not any(token in lowered for token in keywords):
            continue
        cleaned = _clean_phrase(line, max_len=170)
        if len(cleaned.split()) < 4:
            continue
        if cleaned not in picked:
            picked.append(cleaned)
        if len(picked) >= 6:
            break

    if picked:
        return picked

    # Fallback to sentence-level extraction.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw_text or "") if s.strip()]
    for sentence in sentences:
        lowered = sentence.lower()
        if any(token in lowered for token in keywords):
            cleaned = _clean_phrase(sentence, max_len=170)
            if cleaned not in picked:
                picked.append(cleaned)
        if len(picked) >= 6:
            break

    return picked


def _build_simple_overview(company_name: str, role_title: str, required_skills: list[str]) -> str:
    if required_skills:
        top_skills = ", ".join(required_skills[:5])
        return (
            f"{company_name} is hiring for {role_title}. In simple terms, they need candidates with practical knowledge in "
            f"{top_skills}, along with clear communication and role readiness."
        )

    return (
        f"{company_name} is hiring for {role_title}. In simple terms, this JD focuses on role-specific responsibilities, "
        "problem solving, and clear communication during interviews."
    )


def _build_preparation_tips(required_skills: list[str], key_requirements: list[str]) -> list[str]:
    tips: list[str] = []
    if required_skills:
        tips.append(f"Prepare short examples for these skills: {', '.join(required_skills[:4])}.")
    tips.append("Keep one project story ready: problem, what you did, and final result.")
    tips.append("Align your resume wording with the exact JD terms for better clarity.")
    if key_requirements:
        tips.append("Read the mandatory requirements first and answer interview questions around them.")
    return tips[:4]


def _is_role_like_phrase(value: str) -> bool:
    lowered = value.lower()
    role_tokens = (
        "intern",
        "developer",
        "engineer",
        "analyst",
        "manager",
        "specialist",
        "associate",
        "lead",
        "tester",
        "architect",
    )
    return any(token in lowered for token in role_tokens)


def _build_fallback_payload(
    company_name: str,
    role_title: str,
    required_skills: list[str],
    key_requirements: list[str],
) -> dict[str, Any]:
    overview = _build_simple_overview(company_name, role_title, required_skills)
    what_to_prepare = _build_preparation_tips(required_skills, key_requirements)
    return {
        "company_name": company_name,
        "role_title": role_title,
        "overview": overview,
        "required_skills": required_skills,
        "key_requirements": key_requirements,
        "what_to_prepare": what_to_prepare,
        "generated_by": "fallback",
    }


def _pick_identity_value(*, primary: str, secondary: str, placeholder: str) -> str:
    if primary and primary != placeholder:
        return primary
    if secondary and secondary != placeholder:
        return secondary
    return placeholder


def _coerce_company_candidate(value: str) -> str:
    candidate = _normalize_company_candidate(_clean_phrase(str(value or ""), max_len=60))
    if _is_valid_company_candidate(candidate):
        return candidate
    return _COMPANY_PLACEHOLDER


def _coerce_role_candidate(value: str) -> str:
    candidate = _clean_phrase(str(value or ""), max_len=80)
    if _is_valid_role_candidate(candidate):
        return candidate
    return _ROLE_PLACEHOLDER


def _is_valid_company_candidate(value: str) -> bool:
    candidate = _clean_phrase(value, max_len=60)
    if not candidate:
        return False

    lowered = candidate.lower()
    if lowered in {"", _COMPANY_PLACEHOLDER}:
        return False
    if any(token in lowered for token in _COMPANY_REJECT_TOKENS):
        return False
    if re.search(r"\b(campus|drive|batch|freshers?|students?)\b", lowered):
        return False
    if any(token in lowered for token in _SALARY_TOKENS):
        return False
    if re.search(r"\d+\s*(?:lpa|ctc)", lowered):
        return False
    if "." in candidate and len(candidate.split()) > 4:
        return False
    if len(candidate.split()) > 6:
        return False
    if _is_role_like_phrase(candidate):
        return False

    return True


def _is_valid_role_candidate(value: str) -> bool:
    candidate = _clean_phrase(value, max_len=80)
    if not candidate:
        return False

    lowered = candidate.lower()
    if lowered in {"", _ROLE_PLACEHOLDER}:
        return False
    if any(token in lowered for token in _ROLE_REJECT_TOKENS):
        return False
    if any(token in lowered for token in _SALARY_TOKENS):
        return False
    if re.search(r"\d+\s*(?:lpa|ctc)", lowered):
        return False
    if len(candidate.split()) > 8:
        return False

    has_role_keyword = any(token in lowered for token in _ROLE_KEYWORDS)
    has_level_marker = bool(re.search(r"\b(?:l\d|level\s*\d+)\b", lowered))
    if not has_role_keyword and not has_level_marker:
        return False

    if not has_role_keyword and has_level_marker and len(candidate.split()) < 2:
        return False

    return True


def _normalize_company_candidate(value: str) -> str:
    candidate = _clean_phrase(value, max_len=60)
    if not candidate:
        return ""

    cleaned = re.sub(
        r"\b(campus\s*drive|campus|drive|hiring|recruitment|batch\s*\d{2,4}|freshers?|students?)\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip(" ,;:-")

    return cleaned or candidate


def _clean_phrase(value: str, max_len: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:-")
    if len(text) <= max_len:
        return text
    window = text[: max_len + 1]
    cut = window.rfind(" ")
    if cut >= int(max_len * 0.6):
        return window[:cut].strip(" ,;:-")
    return text[:max_len].strip(" ,;:-")


def _clean_list(value: Any, *, max_items: int, max_len: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _clean_phrase(str(item or ""), max_len=max_len)
        if not text:
            continue
        if text.lower() in {entry.lower() for entry in cleaned}:
            continue
        cleaned.append(text)
        if len(cleaned) >= max_items:
            break
    return cleaned
