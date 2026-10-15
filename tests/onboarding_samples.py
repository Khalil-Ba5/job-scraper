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
