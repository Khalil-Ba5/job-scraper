"""Applications per week: this week against last, with filters."""
from datetime import date, datetime, timezone

from review import weekly

UTC = timezone.utc
# A Wednesday.
TODAY = date(2026, 10, 14)


def _job(day, score=60, stage="applied", title="Data Engineer", company="Acme"):
    return {"job_id": f"{day}-{score}", "resume_score": score, "application_stage": stage,
            "job_title": title, "company": company,
            "application_date": datetime(day.year, day.month, day.day, 10, tzinfo=UTC).isoformat()}


def _summary(jobs, **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("tz", UTC)
    return weekly.summarize(jobs, **kw)


class TestWeekStart:
    def test_monday_week(self):
        assert weekly.week_start(TODAY, 0) == date(2026, 10, 12)

    def test_sunday_week(self):
        assert weekly.week_start(TODAY, 6) == date(2026, 10, 11)

    def test_first_day_is_its_own_start(self):
        assert weekly.week_start(date(2026, 10, 12), 0) == date(2026, 10, 12)


class TestSummarize:
    def test_counts_this_week_and_last(self):
        jobs = [_job(date(2026, 10, 12)), _job(date(2026, 10, 14)),
                _job(date(2026, 10, 5)), _job(date(2026, 10, 9))]
        s = _summary(jobs, compare="full")
        assert s["this_week"] == 2
        assert s["last_week"] == 2
        assert s["delta"] == 0

    def test_pace_only_counts_last_week_up_to_same_weekday(self):
        # Last Mon and last Wed count; last Thu does not — it is Wednesday now.
        jobs = [_job(date(2026, 10, 5)), _job(date(2026, 10, 7)), _job(date(2026, 10, 8))]
        s = _summary(jobs, compare="pace")
        assert s["last_week"] == 2
        assert s["last_week_full"] == 3
        assert s["days_elapsed"] == 3

    def test_history_oldest_first_current_last(self):
        jobs = [_job(date(2026, 9, 28)), _job(date(2026, 10, 13))]
        s = _summary(jobs, weeks=3)
        assert [h["start"] for h in s["history"]] == [
            date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12)]
        assert [h["n"] for h in s["history"]] == [1, 0, 1]
        assert s["average"] == 0.5

    def test_sunday_start_moves_the_boundary(self):
        jobs = [_job(date(2026, 10, 11))]  # a Sunday
        assert _summary(jobs, start_weekday=0)["this_week"] == 0
        assert _summary(jobs, start_weekday=6)["this_week"] == 1

    def test_goal_left(self):
        jobs = [_job(date(2026, 10, 13))]
        assert _summary(jobs, goal=10)["goal_left"] == 9
        assert _summary(jobs, goal=0)["goal_left"] is None
        assert _summary(jobs, goal=1)["goal_left"] == 0

    def test_undated_applications_are_ignored(self):
        assert _summary([{"job_id": "x", "application_date": None}])["this_week"] == 0

    def test_dates_are_bucketed_in_the_given_timezone(self):
        from datetime import timedelta
        berlin = timezone(timedelta(hours=2))
        # 23:30 UTC Sunday is already Monday in Berlin.
        job = {"application_date": "2026-10-11T23:30:00+00:00"}
        assert _summary([job], tz=UTC)["this_week"] == 0
        assert _summary([job], tz=berlin)["this_week"] == 1


class TestFilters:
    def test_min_score_drops_unscored(self):
        jobs = [_job(TODAY, score=80), _job(TODAY, score=50), _job(TODAY, score=None)]
        assert len(weekly.filter_jobs(jobs, min_score=70)) == 1
        assert len(weekly.filter_jobs(jobs, min_score=0)) == 3

    def test_stage(self):
        jobs = [_job(TODAY, stage="applied"), _job(TODAY, stage="interview_1"),
                _job(TODAY, stage="rejected"), _job(TODAY, stage="spam_or_removed")]
        assert len(weekly.filter_jobs(jobs, stage="open")) == 1
        assert len(weekly.filter_jobs(jobs, stage="interview")) == 1
        assert len(weekly.filter_jobs(jobs, stage="closed")) == 1
        assert len(weekly.filter_jobs(jobs, stage="all")) == 4

    def test_term_matches_title_or_company(self):
        jobs = [_job(TODAY, title="ML Engineer"), _job(TODAY, company="Zalando")]
        assert len(weekly.filter_jobs(jobs, term="ml")) == 1
        assert len(weekly.filter_jobs(jobs, term="ZALANDO")) == 1
        assert len(weekly.filter_jobs(jobs, term="")) == 2


class TestSettings:
    def test_missing_file_gives_defaults(self, tmp_path):
        assert weekly.load_settings(str(tmp_path / "nope.json")) == weekly.DEFAULT_SETTINGS

    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "s.json")
        weekly.save_settings({**weekly.DEFAULT_SETTINGS, "goal": 15, "week_start": "Sunday"}, path)
        loaded = weekly.load_settings(path)
        assert loaded["goal"] == 15
        assert loaded["week_start"] == "Sunday"

    def test_bad_values_fall_back(self, tmp_path):
        path = tmp_path / "s.json"
        path.write_text('{"week_start": "Friday", "compare": "x", "junk": 1}', encoding="utf-8")
        loaded = weekly.load_settings(str(path))
        assert loaded["week_start"] == "Monday"
        assert loaded["compare"] == "pace"
        assert "junk" not in loaded

    def test_corrupt_file_gives_defaults(self, tmp_path):
        path = tmp_path / "s.json"
        path.write_text("{not json", encoding="utf-8")
        assert weekly.load_settings(str(path)) == weekly.DEFAULT_SETTINGS
