"""
Applications sent per week: this week against last week, and the weeks before.

Volume is the number that moved the search (see the README), so this counts
sends, not outcomes. Every knob — which day a week starts on, whether last week
is compared in full or only up to today's weekday, which applications count —
is a parameter, so ui_app.py can expose them as settings.

Streamlit-free, like calibration.py — ui_app.py only renders what comes back.
"""
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any, Dict, List, Optional

from review import calibration

# Your own preferences, written by the "Customize" popover. Gitignored: it is a
# per-install choice, not project config.
SETTINGS_PATH = "weekly_settings.json"

DEFAULT_SETTINGS = {
    "week_start": "Monday",
    "compare": "pace",
    "goal": int(os.getenv("WEEKLY_APPLICATION_GOAL", "0")),
    "weeks": 8,
}

WEEK_STARTS = {"Monday": 0, "Sunday": 6}

# "pace": last week counted only up to the same point in the week, so a
# Tuesday is not judged against a whole finished week. "full": all of it.
COMPARE_MODES = {"pace": "Same point last week", "full": "All of last week"}

STAGE_FILTERS = {
    "all": "Any stage",
    "open": "Still open",
    "interview": "Got an interview",
    "closed": "Rejected / ghosted",
}


def load_settings(path: Optional[str] = None) -> Dict[str, Any]:
    """Saved preferences over the defaults. A missing or broken file means defaults."""
    path = path or SETTINGS_PATH
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    except FileNotFoundError:
        return settings
    except (OSError, ValueError) as e:
        logging.warning(f"Ignoring unreadable {path}: {e}")
        return settings
    if isinstance(saved, dict):
        settings.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    if settings["week_start"] not in WEEK_STARTS:
        settings["week_start"] = DEFAULT_SETTINGS["week_start"]
    if settings["compare"] not in COMPARE_MODES:
        settings["compare"] = DEFAULT_SETTINGS["compare"]
    return settings


def save_settings(settings: Dict[str, Any], path: Optional[str] = None) -> None:
    path = path or SETTINGS_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: settings[k] for k in DEFAULT_SETTINGS if k in settings}, f, indent=2)


def applied_on(job: Dict[str, Any], tz: Optional[tzinfo] = None) -> Optional[date]:
    """The calendar day the application went out, in `tz` (local if None)."""
    stamp = calibration._parse_ts(job.get("application_date"))
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(tz).date()


def week_start(day: date, start_weekday: int = 0) -> date:
    """First day of the week containing `day`. 0 = Monday … 6 = Sunday."""
    return day - timedelta(days=(day.weekday() - start_weekday) % 7)


def matches(job: Dict[str, Any], min_score: int = 0, stage: str = "all",
            term: str = "") -> bool:
    """True if the application passes every filter. Unscored jobs fail a min_score > 0."""
    if min_score > 0 and (job.get("resume_score") or 0) < min_score:
        return False
    if stage == "open" and (calibration.is_resolved(job) or calibration.is_excluded(job)):
        return False
    if stage == "interview" and not calibration.got_interview(job):
        return False
    if stage == "closed" and (job.get("application_stage") or "") not in ("rejected", "ghosted"):
        return False
    term = (term or "").strip().lower()
    if term:
        text = f"{job.get('job_title') or ''} {job.get('company') or ''}".lower()
        if term not in text:
            return False
    return True


def filter_jobs(jobs: List[Dict[str, Any]], **filters) -> List[Dict[str, Any]]:
    return [j for j in jobs if matches(j, **filters)]


def summarize(jobs: List[Dict[str, Any]], weeks: int = 8, start_weekday: int = 0,
              compare: str = "pace", goal: int = 0, today: Optional[date] = None,
              tz: Optional[tzinfo] = None) -> Dict[str, Any]:
    """
    Counts for the current week, last week, and `weeks` weeks of history.

    history: oldest first, the current week last; each {"start", "n"}.
    last_week: the comparison figure, per `compare`.
    delta: this_week - last_week.
    goal_left: sends still needed this week to hit `goal` (None if no goal).
    """
    today = today or datetime.now(tz).date()
    current = week_start(today, start_weekday)
    elapsed = (today - current).days  # 0 on the first day of the week

    days = [d for d in (applied_on(j, tz) for j in jobs) if d is not None]
    starts = [current - timedelta(weeks=i) for i in range(max(weeks, 2) - 1, -1, -1)]
    history = [{"start": s, "n": sum(1 for d in days if s <= d < s + timedelta(days=7))}
               for s in starts]

    this_week = history[-1]["n"]
    previous = current - timedelta(weeks=1)
    cutoff = previous + timedelta(days=elapsed + 1 if compare == "pace" else 7)
    last_week = sum(1 for d in days if previous <= d < cutoff)

    return {
        "this_week": this_week,
        "last_week": last_week,
        "last_week_full": history[-2]["n"],
        "delta": this_week - last_week,
        "days_elapsed": elapsed + 1,
        "week_start": current,
        "history": history[-weeks:] if weeks >= 1 else history[-1:],
        "average": (sum(h["n"] for h in history[:-1]) / (len(history) - 1)) if len(history) > 1 else 0,
        "goal": goal,
        "goal_left": max(goal - this_week, 0) if goal > 0 else None,
    }
