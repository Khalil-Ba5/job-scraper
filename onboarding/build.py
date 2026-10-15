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
from typing import Any, Dict, List, Mapping, Optional, Tuple

import config
from onboarding.draft import LEDGER_KEYS, LanguageLevel, OnboardingDraft, Place, SkillTier

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
    text = str(value or "").strip().lower()
    return text in ("y", "true", "1") or text.startswith(("yes", "ja"))


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
    level_answers = {key.split(":", 1)[1].strip().lower(): value for key, value in a.items()
                     if key.startswith("language_level:") and value}
    languages = [(lang.language, level_answers.get(lang.language.strip().lower()) or lang.level
                  or "level not stated") for lang in draft.languages]
    lines += [f"- {esc(name)}: {esc(level)}" for name, level in languages] or ["- not stated"]
    lines += [
        "", "### Location",
        f"- Base: {esc(_place(draft) or 'not stated')}",
        f"- Willing to relocate to: {esc(a.get('relocation'))}",
        "- Remote OK: yes" if _yes(a.get("remote_ok")) else "- Remote OK: no, on-site or hybrid only",
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
    # Serialise both, write both to temporary files, and only then swap them in:
    # a failure anywhere before the swap leaves both originals untouched, so the
    # profile and the answers never end up from two different saves.
    targets = [(profile_path or config.CANDIDATE_PROFILE_PATH,
                json.dumps(profile, indent=2, ensure_ascii=False)),
               (answers_path or config.APPLICATION_ANSWERS_PATH,
                json.dumps(app_answers, indent=2, ensure_ascii=False))]
    written = []
    try:
        for path, text in targets:
            with open(path + ".tmp", "w", encoding="utf-8") as fh:
                fh.write(text)
            written.append(path)
    except OSError:
        for path in written:
            os.remove(path + ".tmp")
        raise
    for path, _ in targets:
        # Only the first backup is kept: it is the file from before the Set up page
        # ever wrote here (usually hand-written), which a second save must not lose.
        if os.path.exists(path) and not os.path.exists(path + ".bak"):
            shutil.copyfile(path, path + ".bak")
    for path, _ in targets:
        os.replace(path + ".tmp", path)


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
    remote = re.search(r"^- Remote OK:\s*(yes|no)", text, re.M | re.I)
    if remote:
        out["remote_ok"] = remote.group(1).lower()
    extras = [skill for skill, tier in _evidence(text) if tier == 4]
    if extras:
        out["extra_skills"] = ", ".join(extras)
    for key, source in _ANSWER_KEYS.items():
        value = str((app_answers or {}).get(source) or "").strip()
        if value and not value.startswith("<") and key not in out:
            out[key] = value
    return out


# ── reading a saved profile back ─────────────────────────────────────────────
def _sections(text: str) -> Dict[str, List[str]]:
    """profile_v2 split by its "### " headings, keyed by the heading in lower case."""
    out: Dict[str, List[str]] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("### "):
            current = line[4:].strip().lower()
            out[current] = []
        elif current:
            out[current].append(line)
    return out


def _section(text: str, prefix: str) -> List[str]:
    return next((lines for heading, lines in _sections(text).items()
                 if heading.startswith(prefix)), [])


def _evidence(text: str) -> List[Tuple[str, int]]:
    out = []
    for line in _section(text, "evidence"):
        match = re.match(r"^- (.+?):\s*tier_(\d)", line)
        if match and not match.group(1).startswith("<"):
            out.append((_unesc(match.group(1).strip()), int(match.group(2))))
    return out


def existing_ledger(profile: Optional[Mapping[str, Any]]) -> Optional[Dict[str, int]]:
    ledger = (profile or {}).get("experience_ledger") or {}
    if all(isinstance(ledger.get(key), int) for key in LEDGER_KEYS):
        return {key: ledger[key] for key in LEDGER_KEYS}
    return None


def draft_from_existing(profile: Mapping[str, Any]) -> OnboardingDraft:
    """A draft rebuilt from a saved profile, so it can be edited without reading the CV again.

    It carries what build_profile needs and the answers cannot supply: the
    summary, languages, location and CV-judged skills. Text it cannot place is
    not carried over; the original file is kept as .bak on the next save.
    """
    text = str(profile.get("profile_v2") or "")
    languages = []
    for line in _section(text, "languages"):
        match = re.match(r"^- (.+?):\s*(.+)$", line)
        if match and not match.group(1).startswith("<"):
            level = _unesc(match.group(2).strip())
            languages.append(LanguageLevel(language=_unesc(match.group(1).strip()),
                                           level="" if level == "level not stated" else level))
    place = Place()
    for line in _section(text, "location"):
        match = re.match(r"^- Base:\s*(.+)$", line)
        if match and not match.group(1).startswith(("<", "not stated")):
            city, _, country = _unesc(match.group(1).strip()).rpartition(",")
            place = Place(city=(city or country).strip(), country=country.strip() if city else "")
    skills = [SkillTier(skill=skill, tier=tier) for skill, tier in _evidence(text) if tier != 4]
    return OnboardingDraft(short_profile=str(profile.get("short_profile") or ""),
                           languages=languages, location=place, skills=skills)


def effective_fte_years(ledger: Mapping[str, int]) -> float:
    """Same formula as scoring/score_jobs.py: part-time and intern time count half."""
    return round((ledger["full_time_professional_months"]
                  + 0.5 * (ledger["working_student_months"] + ledger["internship_months"]
                           + ledger["thesis_or_research_months"])) / 12, 1)


def profile_notes(profile: Mapping[str, Any]) -> str:
    """short_profile and profile_v2 as a reader should see them: placeholders filled in.

    For prompts that quote the profile rather than score with it (the CV-fit
    report, the tailor's fact seeding). The raw template would show {{escaped}}
    braces and unfilled {placeholders}.
    """
    text = str(profile.get("profile_v2") or "")
    ledger = existing_ledger(profile)
    rendered = None
    if ledger is not None:
        try:
            rendered = text.format(effective_fte_years=effective_fte_years(ledger), **ledger)
        except (KeyError, IndexError, ValueError):
            rendered = None
    if rendered is None:
        rendered = _unesc(text)
    return "\n".join(part for part in (str(profile.get("short_profile") or ""), rendered) if part)
