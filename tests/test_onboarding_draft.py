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
