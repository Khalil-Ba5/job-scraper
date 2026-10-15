"""The one LLM call that turns a CV into a draft profile, and the arithmetic around it.

Cheap by construction: one call on ONBOARDING_MODEL returns the parsed CV, a draft
of every profile field the CV can settle, and the questions for the rest.

Months of experience are counted here, from the role dates, rather than by the
model. The scorer's seniority judgement rests on them, and arithmetic is the one
thing a model will state confidently and wrongly. A role whose dates cannot be
read becomes a question; it is never silently counted as zero.

Streamlit-free, like review/apply_queue.py.
"""
import io
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Mapping, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator

import config
import models
from onboarding.questions import prompt_field_list

ROLE_KINDS = ("full_time", "working_student", "internship", "thesis_or_research")
ROLE_KIND_LABELS = {
    "full_time": "Full-time job",
    "working_student": "Working student (Werkstudent)",
    "internship": "Internship",
    "thesis_or_research": "Thesis or research",
}
LEDGER_KEYS = ("full_time_professional_months", "working_student_months",
               "internship_months", "thesis_or_research_months")
KIND_TO_LEDGER = dict(zip(ROLE_KINDS, LEDGER_KEYS))
QUESTION_TYPES = ("date", "yes_no", "choice", "text")
# Nine required fields can all be unknown from a CV; the rest of the budget is for
# the CV's own ambiguities. Anything past this is dropped, and the fallback
# questions cover whatever that leaves unasked.
MAX_QUESTIONS = 12


class RoleKind(BaseModel):
    index: int
    kind: str = "full_time"
    confident: bool = True

    @model_validator(mode="after")
    def _known_kind(self):
        if self.kind not in ROLE_KINDS:
            self.kind = "full_time"
            self.confident = False
        return self


class LanguageLevel(BaseModel):
    language: str
    level: str = ""
    confident: bool = True


class Place(BaseModel):
    city: str = ""
    country: str = ""
    confident: bool = True


class SkillTier(BaseModel):
    skill: str
    tier: int = 2
    reason: str = ""

    @field_validator("tier", mode="before")
    @classmethod
    def _clamp(cls, value):
        try:
            return min(5, max(1, int(value)))
        except (TypeError, ValueError):
            return 2


class Question(BaseModel):
    id: str
    field: str
    text: str
    type: str = "text"
    options: List[str] = Field(default_factory=list)
    suggested: str = ""

    @field_validator("suggested", mode="before")
    @classmethod
    def _as_text(cls, value):
        return "" if value is None else str(value)

    @model_validator(mode="after")
    def _known_type(self):
        if self.type not in QUESTION_TYPES or (self.type == "choice" and not self.options):
            self.type = "text"
        return self


class OnboardingDraft(BaseModel):
    resume: models.Resume = Field(default_factory=models.Resume)
    roles: List[RoleKind] = Field(default_factory=list)
    languages: List[LanguageLevel] = Field(default_factory=list)
    location: Place = Field(default_factory=Place)
    short_profile: str = ""
    skills: List[SkillTier] = Field(default_factory=list)
    questions: List[Question] = Field(default_factory=list)


# ── months of experience ─────────────────────────────────────────────────────
_MONTH_NAMES = {"jan": 1, "feb": 2, "mar": 3, "mär": 3, "apr": 4, "may": 5, "mai": 5,
                "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "okt": 10, "nov": 11,
                "dec": 12, "dez": 12}
_PRESENT = {"present", "current", "now", "today", "ongoing", "heute", "bis heute",
            "aktuell", "laufend", "derzeit"}


def parse_month(value, today: date, end: bool = False) -> Optional[date]:
    """The first of the month a CV date names, or None if it cannot be read.

    A bare year is January as a start and December as an end. An end is never
    later than the current month.
    """
    text = str(value or "").strip().lower()
    current = date(today.year, today.month, 1)
    if text in _PRESENT:
        return current
    year = month = None
    if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?", text):
        year, month = int(m[1]), int(m[2])
    elif m := re.fullmatch(r"(?:\d{1,2}[./])?(\d{1,2})[-/.](\d{4})", text):
        month, year = int(m[1]), int(m[2])
    elif m := re.fullmatch(r"([a-zäöü]+)\.?,?\s+(\d{4})", text):
        month, year = _MONTH_NAMES.get(m[1][:3]), int(m[2])
    elif m := re.fullmatch(r"(\d{4})", text):
        year, month = int(m[1]), (12 if end else 1)
    if year is None or month is None or not 1 <= month <= 12:
        return None
    result = date(year, month, 1)
    return min(result, current) if end else result


def role_months(experience: models.Experience, today: date) -> Optional[int]:
    """Whole months in a role, both ends inclusive, or None if its dates cannot be read."""
    start = parse_month(experience.start_date, today)
    end = parse_month(experience.end_date, today, end=True)
    if start is None or end is None or end < start:
        return None
    return (end.year - start.year) * 12 + end.month - start.month + 1


def answer_overrides(answers: Mapping[str, str]) -> Tuple[Dict[int, str], Dict[int, int]]:
    """Role kinds and month counts the user supplied, keyed by experience index."""
    label_to_kind = {label: kind for kind, label in ROLE_KIND_LABELS.items()}
    kinds: Dict[int, str] = {}
    months: Dict[int, int] = {}
    for field, value in answers.items():
        text = str(value or "").strip()
        name, _, index = field.partition(":")
        if not text or not index.isdigit():
            continue
        if name == "role_kind":
            kind = label_to_kind.get(text, text)
            if kind in ROLE_KINDS:
                kinds[int(index)] = kind
        elif name == "role_months":
            digits = re.search(r"\d+", text)
            if digits:
                months[int(index)] = int(digits.group())
    return kinds, months


def experience_ledger(resume: models.Resume, roles: List[RoleKind], today: date,
                      kinds: Optional[Dict[int, str]] = None,
                      months: Optional[Dict[int, int]] = None) -> Tuple[Dict[str, int], List[int]]:
    """Months per ledger key, and the indexes of roles whose length is unknown.

    A role with no kind counts as full-time; one with no readable dates and no
    answered month count is left out and reported instead.
    """
    kind_of = {role.index: role.kind for role in roles}
    kind_of.update(kinds or {})
    ledger = {key: 0 for key in LEDGER_KEYS}
    undatable: List[int] = []
    for i, experience in enumerate(resume.experience):
        n = (months or {}).get(i)
        if n is None:
            n = role_months(experience, today)
        if n is None:
            undatable.append(i)
            continue
        ledger[KIND_TO_LEDGER[kind_of.get(i, "full_time")]] += n
    return ledger, undatable


def code_questions(draft: OnboardingDraft, today: date) -> List[Dict]:
    """Questions added in code, at no cost: roles with no kind, roles with no readable dates."""
    asked = {q.field for q in draft.questions}
    classified = {role.index for role in draft.roles}
    _, undatable = experience_ledger(draft.resume, draft.roles, today)
    out: List[Dict] = []
    for i, experience in enumerate(draft.resume.experience):
        role = f"{experience.job_title or 'The role'} at {experience.company or 'an unnamed employer'}"
        if i in undatable and f"role_months:{i}" not in asked:
            out.append({"id": f"code_months_{i}", "field": f"role_months:{i}", "type": "text",
                        "text": f"{role}: the CV gives no dates I can read. How many months was it?",
                        "options": [], "suggested": ""})
        if i not in classified and f"role_kind:{i}" not in asked:
            out.append({"id": f"code_kind_{i}", "field": f"role_kind:{i}", "type": "choice",
                        "text": f"{role}: what kind of position was it?",
                        "options": list(ROLE_KIND_LABELS.values()), "suggested": ""})
    return out


# ── the one call ─────────────────────────────────────────────────────────────
class OnboardingError(RuntimeError):
    """The CV could not be turned into a draft. The message is written for the user."""


def build_prompt(cv_text: str, today_note: str) -> str:
    kinds = ", ".join(ROLE_KIND_LABELS.values())
    return f"""You are setting up a job seeker's profile from their CV, for a tool that scores
job postings against it. Read the CV once and return everything below in one answer.

{today_note}

Return:
1. resume: the CV as structured data. Only what the text states; never infer or invent.
2. roles: one entry per item in resume.experience, by its 0-based index. kind is one of
   full_time, working_student, internship, thesis_or_research. confident=false when the
   CV does not make the kind clear.
3. languages: every language with its CEFR level (A1-C2) or "native". Leave level empty
   and set confident=false when the CV gives no level.
4. location: where the candidate lives now.
5. short_profile: exactly four lines, starting "- Education:", "- Current role:",
   "- Languages:", "- Career stage:".
6. skills: up to 15 skills with an evidence tier, judged only from the CV:
   1 = shipped in production with a metric stated, 2 = built and working, no metric,
   3 = personal project or coursework.
7. questions: at most {MAX_QUESTIONS}, written to this candidate, referring to their CV.
   First, one question for every required field below that the CV does not settle.
   Then, with any left: a role whose kind is unclear (field "role_kind:<index>", type
   choice, options exactly: {kinds}); a language with no level (field
   "language_level:<language>", type choice, options A1, A2, B1, B2, C1, C2, native).
   Never ask what the CV already states. Put a suggested answer wherever the CV points
   to one: dates as YYYY-MM-DD, yes_no as "yes" or "no", choice as one of the options.

Required fields:
{prompt_field_list()}

CV text:
{cv_text}
"""


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def run_onboarding_call(cv_text: str, client=None, model: Optional[str] = None,
                        today_note: Optional[str] = None) -> OnboardingDraft:
    """The single model call. Raises OnboardingError with a user-facing message."""
    if client is None:
        from scoring.llm_client import screen_client as client
    if today_note is None:
        from scoring.availability import note
        today_note = note()
    try:
        raw = client.generate_content(
            prompt=build_prompt(cv_text, today_note),
            response_format=OnboardingDraft,
            model_override=model or config.ONBOARDING_MODEL,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 - every provider error reaches the user the same way
        raise OnboardingError(f"The model call failed: {exc}") from exc
    if not raw:
        raise OnboardingError("The model returned an empty answer. Try again, or set "
                              "ONBOARDING_MODEL to a stronger model in .env.")
    try:
        draft = OnboardingDraft.model_validate_json(_strip_fences(raw))
    except ValueError as exc:
        raise OnboardingError("The model's answer was not in the expected shape. Try again, "
                              "or set ONBOARDING_MODEL to a stronger model in .env.") from exc
    draft.questions = draft.questions[:MAX_QUESTIONS]
    return draft


# ── keeping the draft ────────────────────────────────────────────────────────
def save_draft(draft: OnboardingDraft, path: Optional[str] = None) -> None:
    with open(path or config.ONBOARDING_DRAFT_PATH, "w", encoding="utf-8") as fh:
        fh.write(draft.model_dump_json(indent=2))


def load_draft(path: Optional[str] = None) -> Optional[OnboardingDraft]:
    path = path or config.ONBOARDING_DRAFT_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return OnboardingDraft.model_validate_json(fh.read())
    except (OSError, ValueError):
        return None


# ── from PDF bytes to a stored draft ─────────────────────────────────────────
@dataclass
class IngestResult:
    draft: OnboardingDraft
    warnings: List[str] = field(default_factory=list)


def extract_text(pdf_bytes: bytes) -> str:
    from resume.resume_parser import extract_text_from_pdf
    return extract_text_from_pdf(io.BytesIO(pdf_bytes)) or ""


def ingest_cv(pdf_bytes: bytes, upload: bool = True, client=None,
              today_note: Optional[str] = None) -> IngestResult:
    """Read a CV PDF, store it and its parse, and keep the draft.

    Only a PDF with no text, or a failed model call, stops it. Storage problems
    are returned as warnings: the profile can still be finished without them.
    """
    from db import supabase_utils
    from resume.resume_parser import normalize_resume_dict

    text = extract_text(pdf_bytes)
    if not text.strip():
        raise OnboardingError("This PDF has no text in it (a scan?). Export the CV again "
                              "from your editor as a PDF and upload that.")
    warnings: List[str] = []
    if upload and not supabase_utils.upload_base_resume_pdf(pdf_bytes):
        warnings.append("Could not store the PDF in Supabase Storage. The profile is not "
                        "affected, but 'Re-read my stored CV' will not find it.")
    draft = run_onboarding_call(text, client=client, today_note=today_note)

    resume_dict = normalize_resume_dict(draft.resume.model_dump())
    if not supabase_utils.save_base_resume(resume_dict):
        warnings.append("Could not save the parsed CV to Supabase. The scorer reads it from "
                        "there, so scoring will not work until this succeeds.")
    try:
        with open(config.BASE_RESUME_PATH, "w", encoding="utf-8") as fh:
            json.dump(resume_dict, fh, indent=4, ensure_ascii=False)
    except OSError as exc:
        warnings.append(f"Could not write {config.BASE_RESUME_PATH}: {exc}")
    try:
        save_draft(draft)
    except OSError:
        warnings.append("Could not keep a local copy of the draft; editing your answers "
                        "later will need another read of the CV.")
    return IngestResult(draft, warnings)
