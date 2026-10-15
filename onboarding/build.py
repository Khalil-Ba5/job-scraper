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
