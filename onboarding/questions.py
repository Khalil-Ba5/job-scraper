"""What the profile needs that a CV cannot say, and how to ask for it.

The model writes the questions, worded from the CV. This module decides which
answers are required, and supplies a fixed fallback question for any required
field the model did not ask about — so a skipped question costs nothing to
recover, and setup still finishes when the model call fails entirely.

Streamlit-free, like review/apply_queue.py.
"""
from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

QUESTION_TYPES = ("date", "yes_no", "choice", "text")


@dataclass(frozen=True)
class FieldSpec:
    key: str
    type: str
    meaning: str
    fallback: str
    optional: bool = False
    options: Tuple[str, ...] = ()


FIELDS: Tuple[FieldSpec, ...] = (
    FieldSpec("earliest_start", "date", "the first day you can start full-time",
              "From which date can you start full-time?"),
    FieldSpec("contract_deadline", "date", "the date by which you must have a signed contract, if any",
              "Is there a date by which you must have a signed contract? Leave empty if not.",
              optional=True),
    FieldSpec("permit_status", "text",
              "current residence or work permit (or citizenship), and whether an employer must do anything",
              "What is your residence or work permit status (or citizenship), and does an "
              "employer need to do anything?"),
    FieldSpec("needs_sponsorship", "yes_no", "whether a full-time job needs visa sponsorship",
              "Do you need visa sponsorship for a full-time job?"),
    FieldSpec("authorized_countries", "text", "countries where you may work without a new permit application",
              "In which countries can you work without a new permit application?"),
    FieldSpec("relocation", "text", "cities or regions you would move to",
              "Where would you relocate for the right job?"),
    FieldSpec("remote_ok", "yes_no", "whether fully remote roles are acceptable",
              "Are fully remote roles fine for you?"),
    FieldSpec("salary_expectation", "text", "gross yearly salary expectation (Gehaltsvorstellung)",
              "What is your gross yearly salary expectation?"),
    FieldSpec("notice_period", "text", "notice period in the current job (Kündigungsfrist)",
              "What is your notice period? Write 'none' if you are not employed."),
    FieldSpec("working_hours", "choice", "full-time, part-time, or either",
              "Full-time, part-time, or either?",
              options=("Vollzeit", "Teilzeit", "Vollzeit oder Teilzeit")),
    FieldSpec("extra_skills", "text", "skills that are true of you but not on the CV, comma-separated",
              "Anything you can do that is not on your CV? Comma-separated; leave empty if none.",
              optional=True),
)
FIELD_BY_KEY: Dict[str, FieldSpec] = {spec.key: spec for spec in FIELDS}


def _answered(value) -> bool:
    return value is not None and str(value).strip() != ""


def missing_fields(answers: Mapping[str, str]) -> List[str]:
    """Required fields with no answer, in catalogue order."""
    return [spec.key for spec in FIELDS
            if not spec.optional and not _answered(answers.get(spec.key))]


def missing_in_form(form_questions: Sequence[Dict], answers: Mapping[str, str]) -> List[str]:
    """Required catalogue fields, plus any months question shown, still unanswered.

    A role whose dates could not be read is left out of the experience ledger
    until its months are given; skipping the question would count it as zero.
    """
    months = [q["field"] for q in form_questions
              if q["field"].startswith("role_months:") and not _answered(answers.get(q["field"]))]
    return missing_fields(answers) + months


def fallback_questions(keys: Sequence[str]) -> List[Dict]:
    """The built-in question for each field key, in the shape the model's questions have."""
    out = []
    for key in keys:
        spec = FIELD_BY_KEY[key]
        out.append({"id": f"fallback_{key}", "field": key, "text": spec.fallback,
                    "type": spec.type, "options": list(spec.options), "suggested": ""})
    return out


def complete_question_set(model_questions: List[Dict], extra: List[Dict]) -> List[Dict]:
    """Model questions, then code questions, then a fallback for every field left uncovered.

    One question per field: the first wording wins, so the model's CV-specific
    phrasing beats the generic fallback.
    """
    out, seen = [], set()
    for q in list(model_questions) + list(extra):
        if q["field"] in seen:
            continue
        seen.add(q["field"])
        spec = FIELD_BY_KEY.get(q["field"])
        if spec:
            # The model words the question; the catalogue decides its type. A start
            # date typed as free text never reaches the scorer's date regex, and a
            # "Yes, after graduation" option would not read as yes.
            q = dict(q, type=spec.type, options=list(spec.options))
        out.append(q)
    out += fallback_questions([spec.key for spec in FIELDS if spec.key not in seen])
    return out


def prompt_field_list() -> str:
    """The catalogue as prompt lines: key, type, whether optional, what it means."""
    lines = []
    for spec in FIELDS:
        optional = " (optional)" if spec.optional else ""
        options = f" Options: {', '.join(spec.options)}." if spec.options else ""
        lines.append(f"- {spec.key} [{spec.type}]{optional}: {spec.meaning}.{options}")
    return "\n".join(lines)
