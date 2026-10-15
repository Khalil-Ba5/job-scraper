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
