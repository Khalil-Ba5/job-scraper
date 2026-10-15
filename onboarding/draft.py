"""The one LLM call that turns a CV into a draft profile, and the arithmetic around it.

Cheap by construction: one call on ONBOARDING_MODEL returns the parsed CV, a draft
of every profile field the CV can settle, and the questions for the rest.

Months of experience are counted here, from the role dates, rather than by the
model. The scorer's seniority judgement rests on them, and arithmetic is the one
thing a model will state confidently and wrongly. A role whose dates cannot be
read becomes a question; it is never silently counted as zero.

Streamlit-free, like review/apply_queue.py.
"""
import re
from datetime import date
from typing import Dict, List, Mapping, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator

import models

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
