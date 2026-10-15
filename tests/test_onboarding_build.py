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
