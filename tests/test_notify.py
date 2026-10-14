"""Email alerts for strong matches — composition and the guards around sending.

Nothing here opens a socket: `send` is the only function that talks to a mail
server, and it is monkeypatched or exercised through its own failure paths.
"""
import smtplib

import pytest

import config
from scoring import notify


def job(job_id, score, title="ML Engineer", company="ACME", url="https://x.test",
        verdict="Strong fit."):
    return {"job_id": job_id, "job_title": title, "company": company,
            "resume_score": score, "job_url": url,
            "score_breakdown": {"one_line_verdict": verdict}}


@pytest.fixture
def mailable(monkeypatch):
    """Credentials present and alerts on, so only the logic under test decides."""
    monkeypatch.setattr(config, "EMAIL_ALERTS_ENABLED", True)
    monkeypatch.setattr(config, "EMAIL_ALERT_MIN_SCORE", 70)
    monkeypatch.setattr(config, "EMAIL_ALERT_MIN_SCORE_ENGLISH", 55)
    monkeypatch.setattr(config, "EMAIL_ALERT_MAX_JOBS", 10)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    monkeypatch.setattr(config, "SMTP_USER", "me@test")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(config, "EMAIL_FROM", "me@test")
    monkeypatch.setattr(config, "EMAIL_TO", "me@test")
    return monkeypatch


class TestAlertWorthy:
    def test_keeps_the_threshold_and_ranks_best_first(self, mailable):
        jobs = [job("a", 71), job("b", 69), job("c", 95)]
        assert [j["job_id"] for j in notify.alert_worthy(jobs)] == ["c", "a"]

    def test_the_threshold_is_inclusive(self, mailable):
        assert notify.alert_worthy([job("a", 70)])

    def test_unscored_jobs_never_trigger_an_alert(self, mailable):
        assert notify.alert_worthy([{"job_id": "a", "resume_score": None}]) == []

    def test_the_threshold_can_be_overridden_per_call(self, mailable):
        assert len(notify.alert_worthy([job("a", 55)], min_score=50)) == 1


class TestBuildMessage:
    def test_a_single_match_names_it_in_the_subject(self, mailable):
        subject, text, body_html = notify.build_message([job("a", 84)])
        assert subject == "New match (84/100): ML Engineer at ACME"
        assert "84/100" in text and "84/100" in body_html
        assert "https://x.test" in text and "https://x.test" in body_html

    def test_several_matches_lead_with_the_count_and_the_best_one(self, mailable):
        subject, _, _ = notify.build_message([job("a", 91), job("b", 72)])
        assert subject.startswith("2 new matches — top 91/100:")

    def test_long_batches_are_capped_with_a_count_of_the_rest(self, mailable):
        mailable.setattr(config, "EMAIL_ALERT_MAX_JOBS", 2)
        jobs = [job(str(i), 90) for i in range(5)]
        _, text, body_html = notify.build_message(jobs)
        assert "and 3 more" in text and "and 3 more" in body_html

    def test_html_is_escaped_so_a_job_title_cannot_inject_markup(self, mailable):
        _, _, body_html = notify.build_message([job("a", 80, title="R&D <script>x</script>")])
        assert "<script>" not in body_html
        assert "R&amp;D" in body_html

    def test_a_job_missing_everything_optional_still_composes(self, mailable):
        """Manual and Arbeitsagentur rows do not always carry a URL or a verdict."""
        subject, text, body_html = notify.build_message(
            [{"job_id": "a", "resume_score": 88}])
        assert "88/100" in subject and "Untitled role" in subject
        assert "Unknown company" in text and "Unknown company" in body_html


class TestMissingSettings:
    def test_names_exactly_what_is_unset(self, mailable):
        mailable.setattr(config, "SMTP_PASSWORD", None)
        mailable.setattr(config, "EMAIL_TO", "")
        assert notify.missing_settings() == ["SMTP_PASSWORD", "EMAIL_TO"]

    def test_nothing_missing_when_fully_configured(self, mailable):
        assert notify.missing_settings() == []

    def test_several_recipients_may_be_listed_in_one_variable(self, mailable):
        mailable.setattr(config, "EMAIL_TO", "a@test, b@test ,")
        assert notify.recipients() == ["a@test", "b@test"]


class TestNotifyMatches:
    def test_sends_once_for_the_whole_batch(self, mailable):
        sent = []
        mailable.setattr(notify, "send", lambda s, t, h: sent.append(s) or True)
        assert notify.notify_matches([job("a", 84), job("b", 71), job("c", 40)]) == 2
        assert len(sent) == 1

    def test_stays_quiet_when_nothing_clears_the_bar(self, mailable):
        mailable.setattr(notify, "send", lambda s, t, h: pytest.fail("should not send"))
        assert notify.notify_matches([job("a", 69)]) == 0

    def test_disabled_means_disabled_even_with_credentials_present(self, mailable):
        mailable.setattr(config, "EMAIL_ALERTS_ENABLED", False)
        mailable.setattr(notify, "send", lambda s, t, h: pytest.fail("should not send"))
        assert notify.notify_matches([job("a", 99)]) == 0

    def test_a_dead_mail_server_costs_the_alert_and_nothing_else(self, mailable):
        """The jobs are already saved; a scoring run must not fail over an email."""
        def boom(*_args, **_kwargs):
            raise smtplib.SMTPServerDisconnected("connection lost")
        mailable.setattr(smtplib, "SMTP", boom)
        assert notify.notify_matches([job("a", 84)]) == 0

    def test_missing_credentials_are_reported_rather_than_raised(self, mailable):
        mailable.setattr(config, "SMTP_PASSWORD", None)
        assert notify.notify_matches([job("a", 84)]) == 0


def english_job(job_id, score, language="en"):
    entry = job(job_id, score)
    entry["score_breakdown"]["jd_language"] = language
    return entry


class TestEnglishAdBar:
    """Both interviews came from English ads scored 58, under the general bar of 70."""

    @pytest.fixture
    def bars(self, mailable):
        mailable.setattr(config, "EMAIL_ALERT_MIN_SCORE_ENGLISH", 55)
        return mailable

    def test_an_english_ad_is_mailed_at_the_lower_bar(self, bars):
        assert [j["job_id"] for j in notify.alert_worthy([english_job("en", 58)])] == ["en"]

    def test_a_german_ad_still_needs_the_general_bar(self, bars):
        assert notify.alert_worthy([english_job("de", 58, "de"), english_job("mx", 69, "mixed")]) == []

    def test_an_ad_with_no_language_needs_the_general_bar(self, bars):
        assert notify.alert_worthy([job("x", 60)]) == []

    def test_the_english_bar_never_sits_above_the_general_one(self, bars):
        bars.setattr(config, "EMAIL_ALERT_MIN_SCORE", 50)
        assert notify.alert_worthy([english_job("en", 52)])

    def test_an_explicit_min_score_overrides_both(self, bars):
        assert notify.alert_worthy([english_job("en", 58)], min_score=60) == []

    def test_a_breakdown_the_scorer_left_without_a_language_is_not_english(self, bars):
        """A dumped ScoreBreakdown always carries jd_language; its default must not be 'en'."""
        from models import ScoreBreakdown
        default = ScoreBreakdown.model_fields["jd_language"].default
        entry = job("x", 60)
        entry["score_breakdown"]["jd_language"] = default
        assert default != "en"
        assert notify.alert_worthy([entry]) == []

    def test_a_skip_under_the_general_bar_is_not_mailed(self, bars):
        """The lower bar must not mail what the scorer or the P(interview) gate ruled out."""
        entry = english_job("en", 58)
        entry["score_breakdown"]["recommendation"] = "skip"
        assert notify.alert_worthy([entry]) == []

    def test_a_gate_negotiable_job_under_the_general_bar_is_mailed(self, bars):
        entry = english_job("en", 58)
        entry["score_breakdown"]["recommendation"] = "apply_if_gate_negotiable"
        assert notify.alert_worthy([entry])

    def test_at_the_general_bar_the_recommendation_does_not_matter(self, bars):
        entry = english_job("en", 72)
        entry["score_breakdown"]["recommendation"] = "skip"
        assert notify.alert_worthy([entry])

    def test_a_mixed_language_ad_keeps_the_general_bar(self, bars):
        assert notify.alert_worthy([english_job("mx", 60, "mixed")]) == []

    def test_the_mail_names_both_bars(self, bars):
        _, text, body_html = notify.build_message([english_job("en", 58)])
        assert "70+ (55+ for English-language ads)" in text
        assert "70+ (55+ for English-language ads)" in body_html
