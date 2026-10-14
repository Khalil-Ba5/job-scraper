"""A tailored CV's score is kept beside the real one, never in its place.

The model rewrote that CV for that posting, so scoring it measures how well the
rewrite echoes the JD. When it overwrote resume_score, the 8 resolved
applications ranked this way (72-82) produced no interview; both interviews
came from jobs the honest score put at 58.
"""
from unittest.mock import MagicMock, patch

import config
from scoring import score_jobs


def _breakdown(score):
    obj = MagicMock()
    obj.overall_score = score
    return obj


def _job(job_id, previous_score):
    return {"job_id": job_id, "job_title": f"Role {job_id}", "company": "valantic",
            "customized_resume_id": f"cr-{job_id}", "resume_link": None,
            "resume_score": previous_score}


def _run(jobs, scores):
    """Run the rescore phase; return (score writes, custom records, alerts)."""
    recorded, sent = [], []
    update = MagicMock(return_value=True)
    with patch.object(score_jobs.supabase_utils, "get_jobs_to_rescore", return_value=jobs), \
         patch.object(score_jobs.supabase_utils, "get_customized_resume", return_value={"name": "N"}), \
         patch.object(score_jobs.supabase_utils, "update_job_score", update), \
         patch.object(score_jobs.supabase_utils, "record_custom_cv_score",
                      side_effect=lambda job_id, score: recorded.append((job_id, score)) or True), \
         patch.object(score_jobs, "format_resume_to_text", return_value="resume"), \
         patch.object(score_jobs, "get_resume_score_from_ai",
                      side_effect=[_breakdown(s) for s in scores]), \
         patch.object(score_jobs.notify, "notify_matches", side_effect=lambda m, **k: sent.extend(m)), \
         patch.object(config, "LLM_REQUEST_DELAY_SECONDS", 0):
        score_jobs.rescore_jobs_with_custom_resume()
    return update, recorded, sent


class TestCustomScoreIsASideFigure:
    def test_resume_score_is_never_overwritten(self):
        update, _, _ = _run([_job("a", 58)], [82])
        update.assert_not_called()

    def test_the_tailored_score_is_recorded_beside_it(self):
        _, recorded, _ = _run([_job("a", 58), _job("b", 40)], [82, 61])
        assert recorded == [("a", 82), ("b", 61)]

    def test_crossing_the_alert_bar_sends_no_mail(self):
        _, _, sent = _run([_job("a", 10)], [95])
        assert sent == []


class TestOffByDefault:
    def test_the_phase_does_not_run_unless_enabled(self, monkeypatch):
        monkeypatch.setattr(config, "RESCORE_WITH_CUSTOM_RESUME", False)
        monkeypatch.setattr(config, "SCREENING_ENABLED", False)
        monkeypatch.setattr(score_jobs.supabase_utils, "get_base_resume", lambda: None)
        monkeypatch.setattr(config, "BASE_RESUME_PATH", "does-not-exist.json")
        rescore = MagicMock()
        monkeypatch.setattr(score_jobs, "rescore_jobs_with_custom_resume", rescore)
        score_jobs.main([])
        rescore.assert_not_called()

    def test_the_default_is_off(self):
        assert config.RESCORE_WITH_CUSTOM_RESUME is False
