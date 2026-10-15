# Profile Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A *Set up* page in the Streamlit app: upload a CV, answer questions written from it, review, save — producing `candidate_profile.json` and `application_answers.json` with one cheap LLM call.

**Architecture:** A new Streamlit-free `onboarding/` package holds everything testable: `questions.py` (required fields, fallbacks), `draft.py` (the one LLM call, month arithmetic, draft persistence, CV ingestion), `build.py` (draft + answers → the two files, validation, prefill), `status.py` (the setup checks). `ui_app.py` only renders. Two small helpers are added to `db/supabase_utils.py`; the empty→"NA" normalisation in `resume/resume_parser.py` becomes a shared function.

**Tech Stack:** Python 3.11+, Pydantic 2, Streamlit 1.65 (`AppTest` for headless UI tests), LiteLLM through the existing `scoring.llm_client.screen_client`, Supabase, pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-profile-onboarding-design.md`

## Global Constraints

- Exactly one LLM call per CV read, on `config.ONBOARDING_MODEL` (default `config.LLM_SCREEN_MODEL`), through `screen_client.generate_content(..., model_override=...)`. Answers are mapped to fields in code — no second call.
- At most 12 model-written questions (`MAX_QUESTIONS = 12`).
- Months of experience are computed in code from role dates, never by the model.
- Every user- or model-provided string written into `profile_v2` has `{`→`{{` and `}`→`}}`; the template's own placeholders (`{full_time_professional_months}`, `{working_student_months}`, `{internship_months}`, `{thesis_or_research_months}`, `{effective_fte_years}`) stay single.
- `profile_v2` must keep the line `- Earliest full-time start: YYYY-MM-DD` — `scoring/score_jobs.py:216` reads it with `r"Earliest full-time start:\s*(\d{4}-\d{2}-\d{2})"`.
- Nothing is written until the profile passes validation; existing files are copied to `<name>.bak` first. `*.json.bak` and `onboarding_draft.json` are gitignored.
- Tests are credential-free: LLM and Supabase are faked. Run every command from the repository root.
- `onboarding/` never imports `streamlit`.

## Review Focus

- **CV dates in a format the parser does not know** ("seit 2023", "2023 – heute") → the role becomes a months question, never a silent 0. Test in Task 2.
- **Braces in an answer** (`"Fiktionsbescheinigung {pending}"`) → saved profile still formats; the text survives. Test in Task 4.
- **A required answer cleared before submit** → named in the missing list, nothing advances. Test in Task 1.
- **Re-running setup over the hand-written example profile** → `<placeholder>` values are not imported as answers. Test in Task 4.
- **Model output off-spec** (tier 7, unknown role kind, `choice` with no options) → normalised, not a crash. Test in Task 2.

---

### Task 1: Config, gitignore, and the required-field catalogue

**Files:**
- Modify: `config.py` (after the `CANDIDATE_PROFILE_PATH = "candidate_profile.json"` line)
- Modify: `.gitignore`
- Create: `onboarding/__init__.py`
- Create: `onboarding/questions.py`
- Test: `tests/test_onboarding_questions.py`

**Interfaces:**
- Produces: `config.ONBOARDING_MODEL: str`, `config.ONBOARDING_DRAFT_PATH: str`;
  `questions.FieldSpec`, `questions.FIELDS: tuple[FieldSpec, ...]`, `questions.FIELD_BY_KEY: dict[str, FieldSpec]`,
  `questions.missing_fields(answers: Mapping[str, str]) -> list[str]`,
  `questions.fallback_questions(keys: Sequence[str]) -> list[dict]`,
  `questions.complete_question_set(model_questions: list[dict], extra: list[dict]) -> list[dict]`,
  `questions.prompt_field_list() -> str`.
  A *question dict* always has keys `id, field, text, type, options, suggested`; `type ∈ {"date","yes_no","choice","text"}`; answers are strings (dates ISO `YYYY-MM-DD`, yes/no as `"yes"`/`"no"`).

- [ ] **Step 1: Write the failing test**

`tests/test_onboarding_questions.py`:

```python
from onboarding import questions


def full_answers():
    return {
        "earliest_start": "2027-01-01", "permit_status": "Blue Card",
        "needs_sponsorship": "no", "authorized_countries": "Germany",
        "relocation": "Berlin", "remote_ok": "yes", "salary_expectation": "60.000 EUR",
        "notice_period": "3 months", "working_hours": "Vollzeit",
    }


class TestMissingFields:
    def test_complete_answers_miss_nothing(self):
        assert questions.missing_fields(full_answers()) == []

    def test_optional_fields_are_never_required(self):
        answers = full_answers()
        assert "contract_deadline" not in answers and "extra_skills" not in answers
        assert questions.missing_fields(answers) == []

    def test_a_cleared_answer_is_missing(self):
        answers = full_answers()
        answers["salary_expectation"] = "   "
        assert questions.missing_fields(answers) == ["salary_expectation"]


class TestQuestionSet:
    def test_every_uncovered_field_gets_its_fallback(self):
        model = [{"id": "q1", "field": "earliest_start", "text": "From when?", "type": "date",
                  "options": [], "suggested": "2027-01-01"}]
        qs = questions.complete_question_set(model, [])
        fields = [q["field"] for q in qs]
        assert fields[0] == "earliest_start"
        assert set(fields) == {f.key for f in questions.FIELDS}
        assert qs[0]["text"] == "From when?"  # the model's wording wins

    def test_a_field_asked_twice_is_shown_once(self):
        a = {"id": "a", "field": "role_kind:0", "text": "A", "type": "text", "options": [], "suggested": ""}
        b = dict(a, id="b", text="B")
        qs = questions.complete_question_set([a], [b])
        assert [q["text"] for q in qs if q["field"] == "role_kind:0"] == ["A"]

    def test_fallbacks_have_the_question_shape(self):
        (q,) = questions.fallback_questions(["working_hours"])
        assert set(q) == {"id", "field", "text", "type", "options", "suggested"}
        assert q["type"] == "choice" and q["options"]


def test_prompt_lists_every_field():
    text = questions.prompt_field_list()
    for spec in questions.FIELDS:
        assert spec.key in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_onboarding_questions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'onboarding'`

- [ ] **Step 3: Write the implementation**

`onboarding/__init__.py`: empty file.

`onboarding/questions.py`:

```python
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
```

In `config.py`, directly after the line `CANDIDATE_PROFILE_PATH = "candidate_profile.json"`, add:

```python

# --- Profile onboarding (the Set up page) ---
# One call reads the CV and drafts the profile. The cheap screening model is
# enough for extraction; point ONBOARDING_MODEL at LLM_MODEL if the parsed CV
# comes back thin.
ONBOARDING_MODEL = os.environ.get("ONBOARDING_MODEL") or LLM_SCREEN_MODEL
# The last draft, kept so that editing answers later needs no second call. It
# holds the parsed CV, so it is gitignored like the profile itself.
ONBOARDING_DRAFT_PATH = "onboarding_draft.json"
```

Append to `.gitignore`:

```
# Written by the Set up page: the parsed-CV draft, and backups of the personal
# files it replaces. Same personal data as the files themselves.
onboarding_draft.json
*.json.bak
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_onboarding_questions.py tests/test_config.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add onboarding/__init__.py onboarding/questions.py tests/test_onboarding_questions.py config.py .gitignore
git commit -m "feat(onboarding): required-field catalogue and fallback questions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Draft models and experience arithmetic

**Files:**
- Create: `onboarding/draft.py`
- Create: `tests/onboarding_samples.py`
- Test: `tests/test_onboarding_draft.py`

**Interfaces:**
- Consumes: `models.Resume`, `models.Experience` (`models.py:11-46`).
- Produces (in `onboarding/draft.py`):
  `ROLE_KINDS`, `ROLE_KIND_LABELS: dict[str, str]`, `LEDGER_KEYS`, `KIND_TO_LEDGER`, `MAX_QUESTIONS = 12`;
  Pydantic models `RoleKind(index, kind, confident)`, `LanguageLevel(language, level, confident)`, `Place(city, country, confident)`, `SkillTier(skill, tier, reason)`, `Question(id, field, text, type, options, suggested)`, `OnboardingDraft(resume, roles, languages, location, short_profile, skills, questions)`;
  `parse_month(value, today: date, end: bool = False) -> date | None`,
  `role_months(experience: models.Experience, today: date) -> int | None`,
  `answer_overrides(answers: Mapping[str, str]) -> tuple[dict[int, str], dict[int, int]]`,
  `experience_ledger(resume, roles, today, kinds=None, months=None) -> tuple[dict[str, int], list[int]]`,
  `code_questions(draft: OnboardingDraft, today: date) -> list[dict]`.
- Produces (in `tests/onboarding_samples.py`): `TODAY`, `make_draft(**overrides) -> OnboardingDraft`, `ANSWERS: dict`, `LEDGER: dict`.

- [ ] **Step 1: Write the shared test sample**

`tests/onboarding_samples.py`:

```python
"""One realistic draft and answer set, shared by the onboarding tests."""
from datetime import date

import models
from onboarding.draft import LanguageLevel, OnboardingDraft, Place, Question, RoleKind, SkillTier

TODAY = date(2026, 10, 15)


def make_draft(**overrides) -> OnboardingDraft:
    resume = models.Resume(
        name="Alex Example", location="Munich, Germany", languages=["English", "German"],
        experience=[
            models.Experience(job_title="ML Engineer", company="Acme",
                              start_date="2024-01", end_date="Present"),
            models.Experience(job_title="Werkstudent Data", company="Bosch",
                              start_date="03/2022", end_date="12/2023"),
            models.Experience(job_title="Intern", company="Siemens",
                              start_date="Jun 2021", end_date="Aug 2021"),
        ])
    data = dict(
        resume=resume,
        roles=[RoleKind(index=0, kind="full_time"), RoleKind(index=1, kind="working_student"),
               RoleKind(index=2, kind="internship")],
        languages=[LanguageLevel(language="English", level="C1"),
                   LanguageLevel(language="German", level="", confident=False)],
        location=Place(city="Munich", country="Germany"),
        short_profile=("- Education: MSc Informatics, TUM\n- Current role: ML Engineer at Acme\n"
                       "- Languages: English (C1), German\n- Career stage: Early-career"),
        skills=[SkillTier(skill="PyTorch", tier=1, reason="metric stated"),
                SkillTier(skill="Kubernetes", tier=3)],
        questions=[
            Question(id="q1", field="earliest_start", type="date", suggested="2027-01-01",
                     text="Your role at Acme is ongoing — from which date could you start?"),
            Question(id="q2", field="language_level:German", type="choice",
                     options=["A1", "A2", "B1", "B2", "C1", "C2", "native"],
                     text="Your CV lists German without a level — which one?"),
        ])
    data.update(overrides)
    return OnboardingDraft(**data)


ANSWERS = {
    "earliest_start": "2027-01-01", "permit_status": "Blue Card holder",
    "needs_sponsorship": "no", "authorized_countries": "Germany", "relocation": "Berlin, Hamburg",
    "remote_ok": "yes", "salary_expectation": "60.000 EUR", "notice_period": "3 months",
    "working_hours": "Vollzeit", "language_level:German": "B1", "extra_skills": "Airflow, dbt",
}

# make_draft() counted at TODAY: 2024-01..2026-10 = 34, 2022-03..2023-12 = 22, Jun-Aug 2021 = 3.
LEDGER = {"full_time_professional_months": 34, "working_student_months": 22,
          "internship_months": 3, "thesis_or_research_months": 0}
```

- [ ] **Step 2: Write the failing test**

`tests/test_onboarding_draft.py`:

```python
from datetime import date

import models
from onboarding import draft as d
from tests.onboarding_samples import LEDGER, TODAY, make_draft


class TestParseMonth:
    def test_formats_seen_in_parsed_cvs(self):
        assert d.parse_month("2024-01", TODAY) == date(2024, 1, 1)
        assert d.parse_month("2024-01-15", TODAY) == date(2024, 1, 1)
        assert d.parse_month("03/2022", TODAY) == date(2022, 3, 1)
        assert d.parse_month("01.03.2022", TODAY) == date(2022, 3, 1)
        assert d.parse_month("Jun 2021", TODAY) == date(2021, 6, 1)
        assert d.parse_month("März 2022", TODAY) == date(2022, 3, 1)
        assert d.parse_month("Sept. 2021", TODAY) == date(2021, 9, 1)

    def test_present_means_this_month(self):
        for word in ("Present", "heute", "bis heute", "current"):
            assert d.parse_month(word, TODAY) == date(2026, 10, 1)

    def test_bare_year_is_january_as_start_and_december_as_end(self):
        assert d.parse_month("2021", TODAY) == date(2021, 1, 1)
        assert d.parse_month("2021", TODAY, end=True) == date(2021, 12, 1)

    def test_an_end_is_never_in_the_future(self):
        assert d.parse_month("2026", TODAY, end=True) == date(2026, 10, 1)

    def test_unknown_text_is_none_not_a_guess(self):
        for text in ("", "NA", "seit 2023", "2023 – heute", "13/2022"):
            assert d.parse_month(text, TODAY) is None, text


class TestLedger:
    def test_months_are_summed_by_kind(self):
        draft = make_draft()
        ledger, undatable = d.experience_ledger(draft.resume, draft.roles, TODAY)
        assert ledger == LEDGER
        assert undatable == []

    def test_undatable_role_is_reported_not_counted_as_zero(self):
        draft = make_draft()
        draft.resume.experience[0].start_date = "seit 2023"
        ledger, undatable = d.experience_ledger(draft.resume, draft.roles, TODAY)
        assert undatable == [0]
        assert ledger["full_time_professional_months"] == 0

    def test_answers_override_kind_and_months(self):
        draft = make_draft()
        draft.resume.experience[0].start_date = "seit 2023"
        kinds, months = d.answer_overrides({"role_kind:0": "Working student (Werkstudent)",
                                            "role_months:0": "about 20 months"})
        ledger, undatable = d.experience_ledger(draft.resume, draft.roles, TODAY, kinds, months)
        assert undatable == []
        assert ledger["working_student_months"] == 22 + 20

    def test_a_role_with_no_kind_counts_as_full_time(self):
        draft = make_draft(roles=[])
        ledger, _ = d.experience_ledger(draft.resume, draft.roles, TODAY)
        assert ledger["full_time_professional_months"] == 34 + 22 + 3


class TestCodeQuestions:
    def test_undatable_and_unclassified_roles_become_questions(self):
        draft = make_draft(roles=[d.RoleKind(index=0, kind="full_time"),
                                  d.RoleKind(index=1, kind="working_student")])
        draft.resume.experience[0].end_date = "2023 – heute"
        fields = [q["field"] for q in d.code_questions(draft, TODAY)]
        assert fields == ["role_months:0", "role_kind:2"]

    def test_a_field_the_model_already_asked_is_not_repeated(self):
        draft = make_draft(roles=[d.RoleKind(index=0, kind="full_time"),
                                  d.RoleKind(index=1, kind="working_student")],
                           questions=[d.Question(id="m", field="role_kind:2", text="?")])
        assert d.code_questions(draft, TODAY) == []


class TestOffSpecModelOutput:
    def test_out_of_range_tier_is_clamped(self):
        assert d.SkillTier(skill="x", tier=7).tier == 5
        assert d.SkillTier(skill="x", tier="nonsense").tier == 2

    def test_unknown_role_kind_becomes_unconfident_full_time(self):
        role = d.RoleKind(index=0, kind="freelance")
        assert role.kind == "full_time" and role.confident is False

    def test_choice_without_options_becomes_text(self):
        assert d.Question(id="x", field="f", text="t", type="choice").type == "text"
        assert d.Question(id="x", field="f", text="t", type="slider").type == "text"

    def test_non_string_suggestion_is_kept_as_text(self):
        assert d.Question(id="x", field="f", text="t", suggested=True).suggested == "True"
        assert d.Question(id="x", field="f", text="t", suggested=None).suggested == ""

    def test_empty_draft_is_valid(self):
        empty = d.OnboardingDraft()
        assert empty.resume == models.Resume() and empty.questions == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_onboarding_draft.py -q`
Expected: FAIL with `ImportError` (`onboarding.draft` does not exist)

- [ ] **Step 4: Write the implementation**

`onboarding/draft.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_onboarding_draft.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add onboarding/draft.py tests/onboarding_samples.py tests/test_onboarding_draft.py
git commit -m "feat(onboarding): draft models and months-of-experience arithmetic

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The LLM call, CV ingestion, and the Supabase helpers

**Files:**
- Modify: `onboarding/draft.py` (append)
- Modify: `resume/resume_parser.py` (extract `normalize_resume_dict`; `main()` uses it)
- Modify: `db/supabase_utils.py` (add two functions after `download_resume_from_storage`)
- Test: `tests/test_onboarding_draft.py` (append), `tests/test_onboarding_supabase.py`

**Interfaces:**
- Consumes: `questions.prompt_field_list()` (Task 1); `OnboardingDraft`, `MAX_QUESTIONS`, `ROLE_KIND_LABELS` (Task 2); `scoring.llm_client.screen_client.generate_content(prompt, system_prompt=None, temperature=1, response_format=None, model_override=None, cache_system=False) -> str`; `scoring.availability.note() -> str`; `resume.resume_parser.extract_text_from_pdf(pdf_path_or_file) -> str`; `supabase_utils.save_base_resume(dict) -> bool`.
- Produces: `draft.OnboardingError(RuntimeError)`, `draft.build_prompt(cv_text: str, today_note: str) -> str`, `draft.run_onboarding_call(cv_text: str, client=None, model: str | None = None, today_note: str | None = None) -> OnboardingDraft`, `draft.save_draft(draft, path=None) -> None`, `draft.load_draft(path=None) -> OnboardingDraft | None`, `draft.extract_text(pdf_bytes: bytes) -> str`, `draft.IngestResult(draft, warnings)`, `draft.ingest_cv(pdf_bytes: bytes, upload: bool = True, client=None, today_note: str | None = None) -> IngestResult`; `resume_parser.normalize_resume_dict(data)`; `supabase_utils.upload_base_resume_pdf(pdf_bytes: bytes, file_name: str = "resume.pdf") -> bool`; `supabase_utils.base_resume_exists() -> bool | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_onboarding_draft.py`:

```python
import json

import pytest

import config


class FakeClient:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.reply


class TestOnboardingCall:
    def test_one_call_on_the_onboarding_model(self, monkeypatch):
        monkeypatch.setattr(config, "ONBOARDING_MODEL", "anthropic/claude-haiku-4-5")
        client = FakeClient(make_draft().model_dump_json())
        result = d.run_onboarding_call("CV TEXT", client=client, today_note="Today is 2026-10-15.")
        assert len(client.calls) == 1
        call = client.calls[0]
        assert call["model_override"] == "anthropic/claude-haiku-4-5"
        assert call["response_format"] is d.OnboardingDraft
        assert "CV TEXT" in call["prompt"] and "Today is 2026-10-15." in call["prompt"]
        assert "salary_expectation" in call["prompt"]  # the required-field list is in it
        assert result.resume.name == "Alex Example"

    def test_code_fences_are_tolerated(self):
        raw = "```json\n" + make_draft().model_dump_json() + "\n```"
        result = d.run_onboarding_call("x", client=FakeClient(raw), today_note="t")
        assert result.location.city == "Munich"

    def test_questions_are_capped(self):
        many = [d.Question(id=str(i), field=f"f{i}", text="?") for i in range(20)]
        raw = make_draft(questions=many).model_dump_json()
        result = d.run_onboarding_call("x", client=FakeClient(raw), today_note="t")
        assert len(result.questions) == d.MAX_QUESTIONS

    @pytest.mark.parametrize("client", [FakeClient(""), FakeClient("not json"),
                                        FakeClient(error=RuntimeError("429 rate limit"))])
    def test_every_failure_is_one_readable_error(self, client):
        with pytest.raises(d.OnboardingError):
            d.run_onboarding_call("x", client=client, today_note="t")


class TestDraftFile:
    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "draft.json")
        d.save_draft(make_draft(), path)
        assert d.load_draft(path) == make_draft()

    def test_missing_or_corrupt_is_none(self, tmp_path):
        assert d.load_draft(str(tmp_path / "nope.json")) is None
        bad = tmp_path / "bad.json"
        bad.write_text("{", encoding="utf-8")
        assert d.load_draft(str(bad)) is None


class TestIngest:
    @pytest.fixture
    def stores(self, monkeypatch, tmp_path):
        from db import supabase_utils
        saved = {}
        monkeypatch.setattr(config, "BASE_RESUME_PATH", str(tmp_path / "resume.json"))
        monkeypatch.setattr(config, "ONBOARDING_DRAFT_PATH", str(tmp_path / "draft.json"))
        monkeypatch.setattr(supabase_utils, "upload_base_resume_pdf",
                            lambda data: saved.setdefault("pdf", data) is not None)
        monkeypatch.setattr(supabase_utils, "save_base_resume",
                            lambda data: saved.setdefault("resume", data) is not None)
        monkeypatch.setattr(d, "extract_text", lambda data: "Alex Example, ML Engineer")
        return saved, tmp_path

    def test_reads_stores_and_keeps_the_draft(self, stores):
        saved, tmp_path = stores
        result = d.ingest_cv(b"%PDF", client=FakeClient(make_draft().model_dump_json()),
                             today_note="t")
        assert result.warnings == []
        assert saved["pdf"] == b"%PDF"
        assert saved["resume"]["email"] == "NA"  # normalised like resume_parser does
        assert json.loads((tmp_path / "resume.json").read_text(encoding="utf-8"))["name"] == "Alex Example"
        assert d.load_draft() == result.draft

    def test_rereading_the_stored_cv_does_not_upload_it_again(self, stores):
        saved, _ = stores
        d.ingest_cv(b"%PDF", upload=False, client=FakeClient(make_draft().model_dump_json()),
                    today_note="t")
        assert "pdf" not in saved

    def test_a_scanned_pdf_stops_before_any_call(self, stores, monkeypatch):
        monkeypatch.setattr(d, "extract_text", lambda data: "  \n")
        client = FakeClient(make_draft().model_dump_json())
        with pytest.raises(d.OnboardingError, match="no text"):
            d.ingest_cv(b"%PDF", client=client, today_note="t")
        assert client.calls == []

    def test_storage_failures_are_warnings_not_stops(self, stores, monkeypatch):
        from db import supabase_utils
        monkeypatch.setattr(supabase_utils, "upload_base_resume_pdf", lambda data: False)
        monkeypatch.setattr(supabase_utils, "save_base_resume", lambda data: False)
        result = d.ingest_cv(b"%PDF", client=FakeClient(make_draft().model_dump_json()),
                             today_note="t")
        assert len(result.warnings) == 2
        assert result.draft.resume.name == "Alex Example"
```

`tests/test_onboarding_supabase.py`:

```python
from unittest.mock import MagicMock

from db import supabase_utils


def test_upload_replaces_resume_pdf(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(supabase_utils, "supabase", fake)
    assert supabase_utils.upload_base_resume_pdf(b"%PDF") is True
    fake.storage.from_.assert_called_with("resumes")
    kwargs = fake.storage.from_.return_value.upload.call_args.kwargs
    assert kwargs["path"] == "resume.pdf" and kwargs["file"] == b"%PDF"
    assert kwargs["file_options"]["upsert"] == "true"


def test_upload_failure_is_false(monkeypatch):
    fake = MagicMock()
    fake.storage.from_.return_value.upload.side_effect = RuntimeError("bucket missing")
    monkeypatch.setattr(supabase_utils, "supabase", fake)
    assert supabase_utils.upload_base_resume_pdf(b"%PDF") is False
    assert supabase_utils.upload_base_resume_pdf(b"") is False


def test_base_resume_exists_three_ways(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(supabase_utils, "supabase", fake)
    query = fake.table.return_value.select.return_value.limit.return_value.execute
    query.return_value = MagicMock(data=[{"id": "x"}])
    assert supabase_utils.base_resume_exists() is True
    query.return_value = MagicMock(data=[])
    assert supabase_utils.base_resume_exists() is False
    query.side_effect = RuntimeError("unreachable")
    assert supabase_utils.base_resume_exists() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_onboarding_draft.py tests/test_onboarding_supabase.py -q`
Expected: FAIL — `AttributeError` on `d.run_onboarding_call`, `supabase_utils.upload_base_resume_pdf`, `supabase_utils.base_resume_exists`

- [ ] **Step 3: Extract `normalize_resume_dict` in `resume/resume_parser.py`**

Add above `def main():`:

```python
def normalize_resume_dict(data):
    """Empty strings and None become "NA", recursively.

    The rest of the pipeline reads "NA" as "the CV does not say"; an empty string
    would read as a value. Shared by the parser and the Set up page.
    """
    if isinstance(data, dict):
        return {key: normalize_resume_dict(value) for key, value in data.items()}
    if isinstance(data, list):
        return [normalize_resume_dict(item) for item in data]
    if data == "" or data is None:
        return "NA"
    return data
```

In `main()`, replace:

```python
        # Recursive function to replace empty values or None with "NA"
        def replace_empty_with_na(data):
            if isinstance(data, dict):
                return {k: replace_empty_with_na(v) for k, v in data.items()}
            elif isinstance(data, list):
                return[replace_empty_with_na(i) for i in data]
            elif data == "" or data is None:
                return "NA"
            return data

        resume_data_dict = replace_empty_with_na(resume_data_dict)
```

with:

```python
        resume_data_dict = normalize_resume_dict(resume_data_dict)
```

- [ ] **Step 4: Add the Supabase helpers**

In `db/supabase_utils.py`, directly after `download_resume_from_storage` (ends with `return None` before `def save_base_resume`), add:

```python
def upload_base_resume_pdf(pdf_bytes: bytes, file_name: str = "resume.pdf") -> bool:
    """
    Stores the user's CV in the 'resumes' bucket, replacing the previous one.
    The Set up page calls this; download_resume_from_storage reads the same file.
    """
    if not pdf_bytes:
        logging.error("Cannot upload an empty CV.")
        return False
    try:
        supabase.storage.from_(config.SUPABASE_RESUME_STORAGE_BUCKET).upload(
            path=file_name,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
        return True
    except Exception as e:
        logging.error(f"Error uploading '{file_name}' to Supabase Storage: {e}")
        return False


def base_resume_exists() -> Optional[bool]:
    """
    Whether a parsed CV is stored: True or False when the table answers, None when
    the database cannot be reached (wrong URL, key, or init.sql not run).
    """
    try:
        response = supabase.table(config.SUPABASE_BASE_RESUME_TABLE_NAME)\
            .select("id")\
            .limit(1)\
            .execute()
        return bool(response.data)
    except Exception as e:
        logging.error(f"Error checking for a base resume: {e}")
        return None
```

- [ ] **Step 5: Append the call and ingestion to `onboarding/draft.py`**

Add to the imports at the top of `onboarding/draft.py`:

```python
import io
import json
import os
from dataclasses import dataclass, field

import config
from onboarding.questions import prompt_field_list
```

(Keep the existing imports; `from typing import ...` stays.) Then append:

```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_onboarding_draft.py tests/test_onboarding_supabase.py -q`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add onboarding/draft.py resume/resume_parser.py db/supabase_utils.py tests/test_onboarding_draft.py tests/test_onboarding_supabase.py
git commit -m "feat(onboarding): one cheap call reads the CV into a draft profile

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Building, validating and saving the two files

**Files:**
- Create: `onboarding/build.py`
- Test: `tests/test_onboarding_build.py`

**Interfaces:**
- Consumes: `OnboardingDraft`, `SkillTier`, `LEDGER_KEYS` (Task 2); `config.CANDIDATE_PROFILE_PATH`, `config.APPLICATION_ANSWERS_PATH`.
- Produces: `build.esc(text) -> str`, `build.build_profile(draft, answers: Mapping[str, str], ledger: Mapping[str, int]) -> dict`, `build.build_answers(answers, draft, existing: dict | None = None) -> dict`, `build.validate_profile(profile: dict) -> None` (raises `ValueError`), `build.save_files(profile, app_answers, profile_path=None, answers_path=None) -> None`, `build.secret_line(profile) -> str`, `build.read_json(path) -> dict | None`, `build.prefill_from_existing(profile: dict | None, app_answers: dict | None) -> dict[str, str]`.

- [ ] **Step 1: Write the failing test**

`tests/test_onboarding_build.py`:

```python
import json
import os

import pytest

from onboarding import build
from tests.onboarding_samples import ANSWERS, LEDGER, make_draft

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "candidate_profile.json.example")
ANSWERS_EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "application_answers.json.example")


def profile(answers=ANSWERS):
    return build.build_profile(make_draft(), answers, LEDGER)


class TestBuildProfile:
    def test_has_the_three_keys_the_scorer_requires(self):
        p = profile()
        assert set(p) == {"short_profile", "experience_ledger", "profile_v2"}
        assert p["experience_ledger"] == LEDGER

    def test_formats_like_the_scorer_formats_it(self):
        p = profile()
        text = p["profile_v2"].format(effective_fte_years=3.9, **p["experience_ledger"])
        assert "- Earliest full-time start: 2027-01-01" in text
        assert "- Full-time professional: 34 months" in text
        assert "- German: B1" in text            # the answer beat the empty draft level
        assert "- English: C1" in text
        assert "- PyTorch: tier_1" in text
        assert "- Airflow: tier_4 (true, not on CV)" in text
        assert "- Needs sponsorship for full-time work: NO" in text
        assert "- Remote OK" in text

    def test_braces_in_answers_survive_formatting(self):
        answers = dict(ANSWERS, permit_status="Fiktionsbescheinigung {pending}")
        p = profile(answers)
        build.validate_profile(p)
        text = p["profile_v2"].format(effective_fte_years=1, **p["experience_ledger"])
        assert "Fiktionsbescheinigung {pending}" in text

    def test_passes_the_scorers_own_loader(self, monkeypatch):
        p = profile()
        monkeypatch.setenv("CANDIDATE_PROFILE_JSON", json.dumps(p))
        from scoring import score_jobs
        loaded = score_jobs._load_candidate_profile()
        loaded["profile_v2"].format(effective_fte_years=1.0, **loaded["experience_ledger"])
        assert score_jobs._EARLIEST_START.search(loaded["profile_v2"]).group(1) == "2027-01-01"


class TestValidate:
    def test_missing_key_is_named(self):
        p = profile()
        del p["profile_v2"]
        with pytest.raises(ValueError, match="profile_v2"):
            build.validate_profile(p)

    def test_negative_months_are_rejected(self):
        p = profile()
        p["experience_ledger"]["internship_months"] = -1
        with pytest.raises(ValueError, match="internship_months"):
            build.validate_profile(p)

    def test_unfillable_template_is_rejected(self):
        p = profile()
        p["profile_v2"] += "{oops}"
        with pytest.raises(ValueError, match="profile_v2"):
            build.validate_profile(p)


class TestAnswersFile:
    def test_keys_and_german_date(self):
        a = build.build_answers(ANSWERS, make_draft())
        assert a["eintrittstermin"] == "ab 01.01.2027"
        assert a["gehaltsvorstellung"] == "60.000 EUR"
        assert a["standort"] == "Munich, Germany"
        assert a["extra"] == {}

    def test_existing_extra_answers_are_kept(self):
        a = build.build_answers(ANSWERS, make_draft(), {"extra": {"Referenzen": "on request"}})
        assert a["extra"] == {"Referenzen": "on request"}


class TestSave:
    def test_writes_both_and_backs_up_the_old(self, tmp_path):
        pp, ap = tmp_path / "p.json", tmp_path / "a.json"
        pp.write_text('{"old": true}', encoding="utf-8")
        build.save_files(profile(), {"x": 1}, str(pp), str(ap))
        assert json.loads(pp.read_text(encoding="utf-8"))["experience_ledger"] == LEDGER
        assert json.loads((tmp_path / "p.json.bak").read_text(encoding="utf-8")) == {"old": True}
        assert json.loads(ap.read_text(encoding="utf-8")) == {"x": 1}

    def test_invalid_profile_writes_nothing(self, tmp_path):
        bad = profile()
        del bad["short_profile"]
        with pytest.raises(ValueError):
            build.save_files(bad, {"x": 1}, str(tmp_path / "p.json"), str(tmp_path / "a.json"))
        assert list(tmp_path.iterdir()) == []

    def test_backups_are_gitignored(self):
        import subprocess
        result = subprocess.run(["git", "check-ignore", "candidate_profile.json.bak"],
                                capture_output=True, text=True)
        assert result.returncode == 0


def test_secret_line_is_one_line_of_the_same_json():
    p = profile()
    line = build.secret_line(p)
    assert "\n" not in line and json.loads(line) == p


class TestPrefill:
    def test_round_trip_from_saved_files(self):
        p = profile()
        a = build.build_answers(ANSWERS, make_draft())
        pre = build.prefill_from_existing(p, a)
        for key in ("earliest_start", "permit_status", "authorized_countries", "relocation",
                    "salary_expectation", "notice_period", "working_hours"):
            assert pre[key] == ANSWERS[key], key
        assert pre["needs_sponsorship"] == "no" and pre["remote_ok"] == "yes"

    def test_example_placeholders_are_not_imported(self):
        pre = build.prefill_from_existing(build.read_json(EXAMPLE), build.read_json(ANSWERS_EXAMPLE))
        assert not any(value.startswith("<") for value in pre.values())
        assert "earliest_start" not in pre and "salary_expectation" not in pre
        assert "needs_sponsorship" not in pre  # "<YES/NO, ...>" is not a "no"

    def test_nothing_to_read(self):
        assert build.prefill_from_existing(None, None) == {}
        assert build.read_json("does-not-exist.json") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_onboarding_build.py -q`
Expected: FAIL with `ImportError` (`onboarding.build` does not exist)

- [ ] **Step 3: Write the implementation**

`onboarding/build.py`:

```python
"""Draft + answers -> candidate_profile.json and application_answers.json.

Pure functions, plus one that writes. The profile has the shape of
candidate_profile.json.example, because scoring/score_jobs.py reads it with
`profile_v2.format(effective_fte_years=..., **experience_ledger)`. Two things
follow: every piece of user or model text in profile_v2 has its braces doubled,
and nothing is written until that format call is known to succeed.

Streamlit-free, like review/apply_queue.py.
"""
import json
import os
import re
import shutil
from datetime import date
from typing import Any, Dict, List, Mapping, Optional

import config
from onboarding.draft import LEDGER_KEYS, OnboardingDraft

TIER_LEGEND = (
    "tier_1 = shipped in production with a metric, on the CV | tier_2 = built and working, "
    "on the CV, no metric |\ntier_3 = personal project/coursework, linkable | tier_4 = true but "
    "not currently written anywhere a reader can see | tier_5 = not done"
)


def esc(text) -> str:
    """Make text safe inside a str.format template."""
    return str(text or "").replace("{", "{{").replace("}", "}}")


def _unesc(text: str) -> str:
    return text.replace("{{", "{").replace("}}", "}")


def _yes(value) -> bool:
    return str(value or "").strip().lower() in ("yes", "y", "ja", "true", "1")


def _split(text) -> List[str]:
    return [part.strip() for part in re.split(r"[,;\n]", str(text or "")) if part.strip()]


def _place(draft: OnboardingDraft) -> str:
    return ", ".join(part for part in (draft.location.city, draft.location.country) if part)


def build_profile(draft: OnboardingDraft, answers: Mapping[str, str],
                  ledger: Mapping[str, int]) -> Dict[str, Any]:
    a = {key: str(value).strip() for key, value in answers.items() if value is not None}
    lines = ["", "### Availability",
             f"- Earliest full-time start: {esc(a.get('earliest_start'))}"]
    if a.get("contract_deadline"):
        lines.append(f"- Hard deadline to have a signed contract: {esc(a['contract_deadline'])}")
    lines += [
        "", "### Work authorization",
        f"- Current status: {esc(a.get('permit_status'))}",
        f"- Needs sponsorship for full-time work: {'YES' if _yes(a.get('needs_sponsorship')) else 'NO'}",
        f"- Authorized without a new application only in: {esc(a.get('authorized_countries'))}",
        "", '### Experience ledger (do NOT sum into one "years of experience" figure)',
        "- Full-time professional: {full_time_professional_months} months",
        "- Working student: {working_student_months} months",
        "- Internship: {internship_months} months",
        "- Thesis / research: {thesis_or_research_months} months",
        "- Effective FTE-years for seniority comparison (part-time/intern time discounted ~50%): "
        "{effective_fte_years}",
        "", "### Languages",
    ]
    languages = [(lang.language, a.get(f"language_level:{lang.language}") or lang.level
                  or "level not stated") for lang in draft.languages]
    lines += [f"- {esc(name)}: {esc(level)}" for name, level in languages] or ["- not stated"]
    lines += [
        "", "### Location",
        f"- Base: {esc(_place(draft) or 'not stated')}",
        f"- Willing to relocate to: {esc(a.get('relocation'))}",
        "- Remote OK" if _yes(a.get("remote_ok")) else "- Remote: no, on-site or hybrid only",
        "", "### Evidence index (what can actually be pointed at, not just plausibly claimed)",
        TIER_LEGEND,
    ]
    lines += [f"- {esc(skill.skill)}: tier_{skill.tier}" for skill in draft.skills]
    lines += [f"- {esc(extra)}: tier_4 (true, not on CV)" for extra in _split(a.get("extra_skills"))]
    return {
        "short_profile": draft.short_profile.strip(),
        "experience_ledger": {key: int(ledger.get(key, 0)) for key in LEDGER_KEYS},
        "profile_v2": "\n".join(lines) + "\n",
    }


def _german_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        return iso


def build_answers(answers: Mapping[str, str], draft: OnboardingDraft,
                  existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    a = {key: str(value).strip() for key, value in answers.items() if value is not None}
    start = a.get("earliest_start", "")
    return {
        "gehaltsvorstellung": a.get("salary_expectation", ""),
        "eintrittstermin": f"ab {_german_date(start)}" if start else "",
        "kuendigungsfrist": a.get("notice_period", ""),
        "aufenthaltstitel": a.get("permit_status", ""),
        "relocation": a.get("relocation", ""),
        "arbeitszeit": a.get("working_hours", ""),
        "standort": _place(draft),
        "extra": dict((existing or {}).get("extra") or {}),
    }


def validate_profile(profile: Mapping[str, Any]) -> None:
    """The scorer's own rules. Raises ValueError naming the first problem."""
    for key in ("short_profile", "experience_ledger", "profile_v2"):
        if key not in profile:
            raise ValueError(f"the profile is missing {key}")
    ledger = profile["experience_ledger"]
    for key in LEDGER_KEYS:
        value = ledger.get(key)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"experience_ledger.{key} must be a whole number of months")
    try:
        profile["profile_v2"].format(effective_fte_years=0, **ledger)
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"profile_v2 cannot be filled in: {exc}") from exc


def save_files(profile: Dict[str, Any], app_answers: Dict[str, Any],
               profile_path: Optional[str] = None, answers_path: Optional[str] = None) -> None:
    """Validate, back up what is there, then write both files."""
    validate_profile(profile)
    targets = ((profile_path or config.CANDIDATE_PROFILE_PATH, profile),
               (answers_path or config.APPLICATION_ANSWERS_PATH, app_answers))
    for path, _ in targets:
        if os.path.exists(path):
            shutil.copyfile(path, path + ".bak")
    for path, data in targets:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)


def secret_line(profile: Mapping[str, Any]) -> str:
    """The profile as one line, for the CANDIDATE_PROFILE_JSON repository secret."""
    return json.dumps(profile, ensure_ascii=False, separators=(",", ":"))


def read_json(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


_PROFILE_LINES = {
    "earliest_start": r"Earliest full-time start:\s*(.+)",
    "contract_deadline": r"Hard deadline to have a signed contract:\s*(.+)",
    "permit_status": r"Current status:\s*(.+)",
    "needs_sponsorship": r"Needs sponsorship for full-time work:\s*(.+)",
    "authorized_countries": r"Authorized without a new application only in:\s*(.+)",
    "relocation": r"Willing to relocate to:\s*(.+)",
}
_ANSWER_KEYS = {"salary_expectation": "gehaltsvorstellung", "notice_period": "kuendigungsfrist",
                "working_hours": "arbeitszeit", "permit_status": "aufenthaltstitel",
                "relocation": "relocation"}


def prefill_from_existing(profile: Optional[Mapping[str, Any]],
                          app_answers: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Form values recovered from the saved files, so the page can be re-run to edit.

    Reads the shape build_profile writes. Anything it cannot find, and any
    "<placeholder>" left from the example files, is simply absent: the question
    is then asked again rather than pre-filled with nonsense.
    """
    out: Dict[str, str] = {}
    text = str((profile or {}).get("profile_v2") or "")
    for key, pattern in _PROFILE_LINES.items():
        match = re.search(pattern, text)
        value = _unesc(match.group(1).strip()) if match else ""
        # Placeholders are dropped before any normalising: "<YES/NO, ...>" must not
        # become a confident "no".
        if value and not value.startswith("<"):
            out[key] = value
    if "needs_sponsorship" in out:
        out["needs_sponsorship"] = "yes" if out["needs_sponsorship"].upper().startswith("YES") else "no"
    if "### Location" in text:
        out["remote_ok"] = "yes" if re.search(r"^- Remote OK", text, re.M) else "no"
    for key, source in _ANSWER_KEYS.items():
        value = str((app_answers or {}).get(source) or "").strip()
        if value and not value.startswith("<") and key not in out:
            out[key] = value
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_onboarding_build.py -q`
Expected: all PASS. (The example file's `- Remote OK` line does yield `remote_ok = "yes"`; that is a real value, not a placeholder, and the test allows it.)

- [ ] **Step 5: Commit**

```bash
git add onboarding/build.py tests/test_onboarding_build.py
git commit -m "feat(onboarding): build, validate and save the profile and answers files

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Setup checks

**Files:**
- Create: `onboarding/status.py`
- Test: `tests/test_onboarding_status.py`

**Interfaces:**
- Consumes: `build.read_json`, `build.validate_profile` (Task 4); `config.CANDIDATE_PROFILE_PATH`.
- Produces: `status.Check(label: str, ok: bool, fix: str)`, `status.provider_key_name(model: str) -> str | None`, `status.env_checks(env: Mapping[str, str], model: str) -> list[Check]` (always two: Supabase settings, LLM key), `status.profile_present(path: str | None = None, env: Mapping | None = None) -> bool`.

- [ ] **Step 1: Write the failing test**

`tests/test_onboarding_status.py`:

```python
import json

from onboarding import status
from tests.onboarding_samples import ANSWERS, LEDGER, make_draft

SUPA = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "k"}


class TestEnvChecks:
    def test_all_set(self):
        checks = status.env_checks(dict(SUPA, ANTHROPIC_API_KEY="sk-ant"), "anthropic/claude-haiku-4-5")
        assert [c.ok for c in checks] == [True, True]

    def test_missing_supabase_names_the_variables(self):
        supa, key = status.env_checks({"ANTHROPIC_API_KEY": "sk"}, "anthropic/x")
        assert not supa.ok and "SUPABASE_URL" in supa.fix
        assert key.ok

    def test_the_key_must_match_the_provider(self):
        _, key = status.env_checks(dict(SUPA, ANTHROPIC_API_KEY="sk"), "openai/gpt-4o-mini")
        assert not key.ok and "OPENAI_API_KEY" in key.fix

    def test_generic_llm_api_key_counts(self):
        _, key = status.env_checks(dict(SUPA, LLM_API_KEY="x"), "groq/llama")
        assert key.ok

    def test_blank_values_do_not_count(self):
        supa, key = status.env_checks({"SUPABASE_URL": " ", "SUPABASE_SERVICE_ROLE_KEY": "k",
                                       "ANTHROPIC_API_KEY": ""}, "anthropic/x")
        assert not supa.ok and not key.ok


class TestProfilePresent:
    def test_a_valid_file(self, tmp_path):
        from onboarding import build
        path = tmp_path / "p.json"
        path.write_text(json.dumps(build.build_profile(make_draft(), ANSWERS, LEDGER)), encoding="utf-8")
        assert status.profile_present(str(path), env={})

    def test_missing_or_broken_file(self, tmp_path):
        assert not status.profile_present(str(tmp_path / "none.json"), env={})
        broken = tmp_path / "b.json"
        broken.write_text('{"short_profile": "x"}', encoding="utf-8")
        assert not status.profile_present(str(broken), env={})

    def test_the_ci_secret_counts(self, tmp_path):
        assert status.profile_present(str(tmp_path / "none.json"),
                                      env={"CANDIDATE_PROFILE_JSON": "{...}"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_onboarding_status.py -q`
Expected: FAIL with `ImportError` (`onboarding.status` does not exist)

- [ ] **Step 3: Write the implementation**

`onboarding/status.py`:

```python
"""What setup still needs, as a row of checks the Set up page draws.

Only things that can be read cheaply on every rerun: environment variables and
local files. The database check lives in the page, because it is a network call.

Streamlit-free, like review/apply_queue.py.
"""
import os
from dataclasses import dataclass
from typing import List, Mapping, Optional

import config
from onboarding import build

PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY", "openrouter": "OPENROUTER_API_KEY",
}


@dataclass(frozen=True)
class Check:
    label: str
    ok: bool
    fix: str


def _set(env: Mapping[str, str], name: str) -> bool:
    return bool(str(env.get(name) or "").strip())


def provider_key_name(model: str) -> Optional[str]:
    provider = model.split("/")[0].lower() if "/" in model else model.lower()
    return PROVIDER_KEYS.get(provider)


def env_checks(env: Mapping[str, str], model: str) -> List[Check]:
    supabase_ok = _set(env, "SUPABASE_URL") and _set(env, "SUPABASE_SERVICE_ROLE_KEY")
    key_name = provider_key_name(model)
    key_ok = (key_name is not None and _set(env, key_name)) or _set(env, "LLM_API_KEY")
    key_fix = (f"Set {key_name} in .env" if key_name
               else f"Set the API key for '{model}' in .env (see docs/configuration.md)")
    return [
        Check("Supabase settings", supabase_ok,
              "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env, then restart the app."),
        Check("LLM key", key_ok, key_fix + ", then restart the app."),
    ]


def profile_present(path: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> bool:
    """A profile the scorer will accept: the CI secret, or a valid local file."""
    env = os.environ if env is None else env
    if _set(env, "CANDIDATE_PROFILE_JSON"):
        return True
    profile = build.read_json(path or config.CANDIDATE_PROFILE_PATH)
    if profile is None:
        return False
    try:
        build.validate_profile(profile)
        return True
    except ValueError:
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_onboarding_status.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add onboarding/status.py tests/test_onboarding_status.py
git commit -m "feat(onboarding): setup checks for the status strip

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The Set up page

**Files:**
- Modify: `ui_app.py` — imports (top), `PAGES` (around line 74), new section before `def main():`, `main()`
- Modify: `tests/test_ui_app.py` — `app` fixture; new `TestSetupPage`

**Interfaces:**
- Consumes: everything from Tasks 1–5; `supabase_utils.base_resume_exists`, `supabase_utils.download_resume_from_storage(file_name) -> bytes | None`; existing UI helpers `html`, `go`, `T.page_header`, `T.kicker`, `T.chip`, `T.BLUE`, `T.PURPLE`, `T.NEUTRAL`.
- Produces: page id `"setup"`; session keys `onb_draft` (`OnboardingDraft | None`), `onb_answers` (`dict`), `onb_step` (`"questions" | "review" | "done"`), `onb_warnings` (`list[str]`), `onb_saved_profile` (`dict`); widget keys `onb_upload`, `onb_read`, `onb_reread`, `onb_form`, `onb_q_<question id>`, `onb_ledger_<ledger key>`, `onb_short`, `onb_skills`, `onb_back`, `onb_save`, `onb_to_queue`, `onb_again`.

- [ ] **Step 1: Keep the existing UI tests on the queue**

The app will open on *Set up* when no valid profile exists, which is the case on any machine without `candidate_profile.json`. In `tests/test_ui_app.py`, add to the imports:

```python
import config
from onboarding import status as onboarding_status
```

and inside the `app` fixture, before `st.cache_data.clear()`:

```python
    # The app opens on Set up when there is no valid profile. These tests are
    # about the other pages, so they run as an already-onboarded user.
    monkeypatch.setattr(onboarding_status, "profile_present", lambda *a, **k: True)
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_ui_app.py`:

```python
class TestSetupPage:
    @pytest.fixture
    def setup_app(self, app, monkeypatch, tmp_path):
        monkeypatch.setattr(supabase_utils, "base_resume_exists", lambda: True)
        monkeypatch.setattr(config, "ONBOARDING_DRAFT_PATH", str(tmp_path / "draft.json"))
        monkeypatch.setattr(config, "CANDIDATE_PROFILE_PATH", str(tmp_path / "profile.json"))
        monkeypatch.setattr(config, "APPLICATION_ANSWERS_PATH", str(tmp_path / "answers.json"))
        app.session_state["page"] = "setup"
        return app

    def test_opens_on_setup_when_there_is_no_profile(self, app, monkeypatch):
        monkeypatch.setattr(onboarding_status, "profile_present", lambda *a, **k: False)
        monkeypatch.setattr(supabase_utils, "base_resume_exists", lambda: False)
        app.run()
        assert not app.exception
        assert app.session_state["page"] == "setup"

    def test_renders_the_upload_and_the_checks_with_no_draft(self, setup_app):
        setup_app.run()
        assert not setup_app.exception
        text = markdown_text(setup_app)
        assert "Supabase settings" in text and "Profile saved" in text
        assert setup_app.button("onb_read").disabled  # nothing uploaded yet

    def test_questions_combine_the_models_and_the_fallbacks(self, setup_app):
        from tests.onboarding_samples import make_draft
        setup_app.session_state["onb_draft"] = make_draft()
        setup_app.run()
        assert not setup_app.exception
        labels = ([w.label for w in setup_app.date_input] + [w.label for w in setup_app.text_input]
                  + [w.label for w in setup_app.selectbox] + [w.label for w in setup_app.radio])
        assert "Your role at Acme is ongoing — from which date could you start?" in labels
        assert "What is your gross yearly salary expectation?" in labels

    def test_a_failed_read_still_leaves_every_question(self, setup_app):
        from onboarding.draft import OnboardingDraft
        from onboarding.questions import FIELDS
        setup_app.session_state["onb_draft"] = OnboardingDraft()
        setup_app.run()
        assert not setup_app.exception
        labels = ([w.label for w in setup_app.date_input] + [w.label for w in setup_app.text_input]
                  + [w.label for w in setup_app.selectbox] + [w.label for w in setup_app.radio])
        for spec in FIELDS:
            assert spec.fallback in labels, spec.key

    def test_save_writes_both_files_and_offers_the_secret(self, setup_app, tmp_path):
        import json
        from tests.onboarding_samples import ANSWERS, make_draft
        setup_app.session_state["onb_draft"] = make_draft()
        setup_app.session_state["onb_answers"] = dict(ANSWERS)
        setup_app.session_state["onb_step"] = "review"
        setup_app.run()
        assert not setup_app.exception
        setup_app.button("onb_save").click().run()
        assert not setup_app.exception
        saved = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
        assert saved["experience_ledger"]["working_student_months"] == 22
        assert (tmp_path / "answers.json").exists()
        assert any('"short_profile"' in c.value for c in setup_app.code)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui_app.py -q -k Setup`
Expected: FAIL — no `setup` page (`KeyError`/assertion on `page`, missing widgets)

- [ ] **Step 4: Wire imports, navigation and routing in `ui_app.py`**

Replace `from datetime import datetime, timezone` with:

```python
from datetime import date, datetime, timezone
```

After `from db import supabase_utils`, add:

```python
from onboarding import build as onboarding_build
from onboarding import draft as onboarding_draft
from onboarding import questions as onboarding_questions
from onboarding import status as onboarding_status
```

Replace `PAGES`:

```python
PAGES = [
    ("Every day", [("queue", "Jobs to apply"), ("tailor", "Write my CV")]),
    ("Every week", [("apps", "Where I applied")]),
    ("Every month", [("cal", "Is the score right?"), ("arch", "Which CV to use")]),
    ("Once", [("setup", "Set up")]),
]
```

In `main()`, replace `st.session_state.setdefault("page", DEFAULT_PAGE)` with:

```python
    # A first run has nothing to score against, so it opens where that is fixed.
    st.session_state.setdefault(
        "page", DEFAULT_PAGE if onboarding_status.profile_present() else "setup")
```

and in the routing chain, before the final `else:`, add:

```python
    elif page == "setup":
        render_setup_page()
```

- [ ] **Step 5: Add the page section to `ui_app.py`**

Insert directly before `def main():` (after the `# ═══...` separator line that precedes it):

```python
# ═══════════════════════════════════════════════════════════════════════════
# Set up
# ═══════════════════════════════════════════════════════════════════════════

LEDGER_LABELS = (
    ("full_time_professional_months", "Full-time"),
    ("working_student_months", "Working student"),
    ("internship_months", "Internship"),
    ("thesis_or_research_months", "Thesis / research"),
)


def setup_checks():
    """The status strip: what is configured, and what to do about what is not."""
    checks = onboarding_status.env_checks(os.environ, config.ONBOARDING_MODEL)
    exists = supabase_utils.base_resume_exists() if checks[0].ok else None
    checks.append(onboarding_status.Check(
        "Database reachable", exists is not None,
        "Check SUPABASE_URL, and run supabase_setup/init.sql in the Supabase SQL editor."))
    checks.append(onboarding_status.Check("CV read", bool(exists), "Upload your CV below."))
    checks.append(onboarding_status.Check(
        "Profile saved", onboarding_status.profile_present(),
        "Answer the questions below and press Save."))
    return checks


def render_setup_strip(checks):
    chips = "".join(
        T.chip(("✓ " if c.ok else "✗ ") + c.label,
               T.BLUE[200] if c.ok else T.PURPLE[200], T.NEUTRAL[900])
        for c in checks)
    html(f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 10px">{chips}</div>')
    for c in checks:
        if not c.ok:
            st.caption(f"{c.label}: {c.fix}")


def current_draft():
    """The draft in this session, else the one kept on disk from an earlier read."""
    if "onb_draft" not in st.session_state:
        st.session_state["onb_draft"] = onboarding_draft.load_draft()
    return st.session_state["onb_draft"]


def read_cv(data, upload):
    """Run the one model call. On failure, open an empty form so setup can still finish."""
    with st.spinner("Reading your CV — one call to the model, usually under half a minute…"):
        try:
            result = onboarding_draft.ingest_cv(data, upload=upload)
            st.session_state["onb_draft"] = result.draft
            st.session_state["onb_warnings"] = result.warnings
        except onboarding_draft.OnboardingError as exc:
            st.session_state["onb_draft"] = onboarding_draft.OnboardingDraft()
            st.session_state["onb_warnings"] = [
                f"{exc} The questions below can be answered by hand instead."]
    st.session_state["onb_step"] = "questions"
    st.session_state.pop("onb_answers", None)
    st.rerun()


def render_setup_upload(draft, can_call):
    with st.container(border=True):
        html(T.kicker("1 · Your CV", T.PURPLE[700]))
        if draft is not None and draft.resume.name:
            st.caption(f"Read from your CV: {draft.resume.name} · "
                       f"{len(draft.resume.experience)} roles. Upload again to start over.")
        pdf = st.file_uploader("Your CV as a PDF", type=["pdf"], key="onb_upload",
                               disabled=not can_call)
        cols = st.columns(2)
        with cols[0]:
            read = st.button("Read this CV", key="onb_read", type="primary", width="stretch",
                             disabled=pdf is None or not can_call)
        with cols[1]:
            reread = st.button("Re-read my stored CV", key="onb_reread", width="stretch",
                               disabled=not can_call,
                               help="Reads the PDF you uploaded before. One cheap model call.")
        if read:
            read_cv(pdf.getvalue(), upload=True)
        if reread:
            stored = supabase_utils.download_resume_from_storage("resume.pdf")
            if not stored:
                st.error("No stored CV found — upload one above.")
                return
            read_cv(stored, upload=False)


def question_widget(q, default):
    key = f"onb_q_{q['id']}"
    if q["type"] == "date":
        try:
            value = date.fromisoformat(default) if default else None
        except ValueError:
            value = None
        picked = st.date_input(q["text"], value=value, key=key, format="YYYY-MM-DD")
        return picked.isoformat() if picked else ""
    if q["type"] == "yes_no":
        options = ["yes", "no"]
        index = options.index(default) if default in options else None
        return st.radio(q["text"], options, index=index, key=key, horizontal=True) or ""
    if q["type"] == "choice" and q.get("options"):
        options = list(q["options"])
        index = options.index(default) if default in options else None
        return st.selectbox(q["text"], options, index=index, key=key,
                            placeholder="Choose…") or ""
    return st.text_input(q["text"], value=default, key=key).strip()


def render_setup_questions(draft):
    asked = [q.model_dump() for q in draft.questions]
    qs = onboarding_questions.complete_question_set(
        asked, onboarding_draft.code_questions(draft, date.today()))
    answers = st.session_state.get("onb_answers") or {}
    prefill = onboarding_build.prefill_from_existing(
        onboarding_build.read_json(config.CANDIDATE_PROFILE_PATH),
        onboarding_build.read_json(config.APPLICATION_ANSWERS_PATH))
    about_cv = [q for q in qs
                if q["field"].split(":")[0] in ("role_kind", "role_months", "language_level")]
    about_you = [q for q in qs if q not in about_cv]

    with st.form("onb_form"):
        html(T.kicker("2 · A few questions", T.PURPLE[700]))
        collected = {}
        for title, group in (("About your CV", about_cv), ("About you", about_you)):
            if not group:
                continue
            st.markdown(f"**{title}**")
            for q in group:
                default = answers.get(q["field"]) or prefill.get(q["field"]) or q.get("suggested") or ""
                collected[q["field"]] = question_widget(q, default)
        submitted = st.form_submit_button("Continue", type="primary")
    if submitted:
        missing = onboarding_questions.missing_fields(collected)
        if missing:
            st.error("Still needed: " + "; ".join(
                onboarding_questions.FIELD_BY_KEY[key].meaning for key in missing))
            return
        st.session_state["onb_answers"] = collected
        st.session_state["onb_step"] = "review"
        st.rerun()


def render_setup_review(draft):
    answers = st.session_state["onb_answers"]
    kinds, months = onboarding_draft.answer_overrides(answers)
    ledger, _ = onboarding_draft.experience_ledger(draft.resume, draft.roles, date.today(),
                                                   kinds, months)
    with st.container(border=True):
        html(T.kicker("3 · Check and save", T.PURPLE[700]))
        st.caption("Months of experience, counted from the dates on your CV.")
        cols = st.columns(len(LEDGER_LABELS))
        for col, (key, label) in zip(cols, LEDGER_LABELS):
            with col:
                ledger[key] = int(st.number_input(label, min_value=0, value=int(ledger[key]),
                                                  step=1, key=f"onb_ledger_{key}"))
        short = st.text_area("Short profile — the scorer reads this first",
                             value=draft.short_profile, key="onb_short")
        rows = pd.DataFrame([{"skill": s.skill, "tier": s.tier} for s in draft.skills],
                            columns=["skill", "tier"])
        edited = st.data_editor(
            rows, key="onb_skills", num_rows="dynamic", width="stretch",
            column_config={"tier": st.column_config.NumberColumn(
                "tier", min_value=1, max_value=5, step=1,
                help="1 shipped with a metric · 2 built, on the CV · 3 project or coursework · "
                     "4 true but not on the CV · 5 not done")})
        skills = [onboarding_draft.SkillTier(skill=str(r["skill"]).strip(),
                                             tier=r["tier"] if pd.notna(r["tier"]) else 2)
                  for r in edited.to_dict("records")
                  if pd.notna(r.get("skill")) and str(r["skill"]).strip()]
        final = draft.model_copy(update={"short_profile": short, "skills": skills})
        profile = onboarding_build.build_profile(final, answers, ledger)
        app_answers = onboarding_build.build_answers(
            answers, final, onboarding_build.read_json(config.APPLICATION_ANSWERS_PATH))
        with st.expander("Preview the two files"):
            st.json(profile)
            st.json(app_answers)
        back, save = st.columns(2)
        with back:
            if st.button("← Change answers", key="onb_back", width="stretch"):
                st.session_state["onb_step"] = "questions"
                st.rerun()
        with save:
            if st.button("Save", key="onb_save", type="primary", width="stretch"):
                try:
                    onboarding_build.save_files(profile, app_answers)
                except (ValueError, OSError) as exc:
                    st.error(f"Nothing was saved: {exc}")
                    return
                st.session_state["onb_saved_profile"] = profile
                st.session_state["onb_step"] = "done"
                st.rerun()


def render_setup_done():
    st.success("Saved candidate_profile.json and application_answers.json. "
               "The next scoring run uses them.")
    profile = st.session_state.get("onb_saved_profile")
    if profile:
        html(T.kicker("For the scheduled runs on GitHub", T.PURPLE[700]))
        st.caption("GitHub → Settings → Secrets and variables → Actions → New repository "
                   "secret. Name: CANDIDATE_PROFILE_JSON. Value:")
        st.code(onboarding_build.secret_line(profile), language=None, wrap_lines=True)
    cols = st.columns(2)
    with cols[0]:
        if st.button("Go to the jobs", key="onb_to_queue", type="primary", width="stretch"):
            go("queue")
            st.rerun()
    with cols[1]:
        if st.button("Change answers", key="onb_again", width="stretch"):
            st.session_state["onb_step"] = "questions"
            st.rerun()


def render_setup_page():
    html(T.page_header("Set up", "Upload your CV and answer a few questions. One cheap "
                                 "model call reads the CV; the rest comes from your answers."))
    for warning in st.session_state.pop("onb_warnings", []):
        st.warning(warning)
    checks = setup_checks()
    render_setup_strip(checks)
    draft = current_draft()
    render_setup_upload(draft, can_call=checks[0].ok and checks[1].ok)
    if draft is None:
        return
    step = st.session_state.get("onb_step", "questions")
    if step == "review" and st.session_state.get("onb_answers"):
        render_setup_review(draft)
    elif step == "done":
        render_setup_done()
    else:
        render_setup_questions(draft)
```

- [ ] **Step 6: Run the UI tests**

Run: `python -m pytest tests/test_ui_app.py -q -p no:cacheprovider`
Expected: all PASS (the existing tests and the five new ones)

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest tests/ -q -p no:cacheprovider`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add ui_app.py tests/test_ui_app.py
git commit -m "feat(ui): Set up page — upload a CV, answer questions, save the profile

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Docs

**Files:**
- Modify: `README.md` (Quick start steps 4–5)
- Modify: `docs/configuration.md` (Optional variables table; *Your personal files*; *Database* step 4)
- Modify: `.env.example` (models block)

**Interfaces:** none.

- [ ] **Step 1: README quick start**

In `README.md`, replace the whole of **4. Add your CV** and **5. Describe yourself** (from `**4. Add your CV**` up to, not including, `**6. Choose what to search for**`) with:

````markdown
**4. Set up your profile in the app**

```bash
streamlit run ui_app.py
```

The app opens on **Set up**. Upload your CV as a PDF; one cheap model call reads
it and writes questions about what it cannot tell (start date, permit, salary…),
with suggested answers filled in. Check the answers, press **Save**, and
`candidate_profile.json` and `application_answers.json` are written for you. The
page also gives you the line to paste into the `CANDIDATE_PROFILE_JSON` GitHub
secret. Re-open **Set up** at any time to change an answer — that costs nothing.

````

Renumber the following steps: **6. Choose what to search for** → **5.**, **7. Run it** → **6.**

- [ ] **Step 2: Configuration reference**

In `docs/configuration.md`, add a row to the *Optional* environment-variable table, after the `LLM_SCREEN_MODEL` row:

```markdown
| `ONBOARDING_MODEL` | `LLM_SCREEN_MODEL` | Model for the Set up page's single CV read. Set it to `LLM_MODEL`'s value if the parsed CV comes back thin |
```

At the start of the *Your personal files* section, before "Each has a committed `.example` next to it", insert:

```markdown
The **Set up** page in the app writes `candidate_profile.json` and
`application_answers.json` for you from your CV and a few answers, and keeps the
previous versions as `.bak`. The manual route below still works.
```

Add to the *Where settings live* table, after the `profile_facts.json` row:

```markdown
| The Set up page's last CV read | `onboarding_draft.json` | No — gitignored |
```

In *Database (Supabase)* step 4, replace the first sentence "Upload your CV as a PDF to the `resumes` storage bucket, then parse it:" with:

```markdown
4. Upload your CV on the app's **Set up** page — it stores and parses it. To do it
   by hand instead, upload the PDF to the `resumes` storage bucket as `resume.pdf`, then:
```

- [ ] **Step 3: `.env.example`**

In `.env.example`, after the `# LLM_SCREEN_MODEL=...` line, add:

```
# ONBOARDING_MODEL=anthropic/claude-haiku-4-5    # the Set up page's one CV read
```

- [ ] **Step 4: Verify links and run the suite once more**

Run: `python -m pytest tests/ -q -p no:cacheprovider`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add README.md docs/configuration.md .env.example
git commit -m "docs: set up through the app's Set up page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
