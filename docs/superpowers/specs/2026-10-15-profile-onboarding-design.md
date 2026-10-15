# Profile onboarding: upload a CV, answer questions written from it

**Date:** 2026-10-15
**Status:** approved design, awaiting spec review

## Goal

Remove every hand-edited setup file. A user uploads their CV in the Streamlit app,
answers a short set of questions the model wrote from that CV, reviews the result,
and saves. The scorer can then run.

**Audience:** the owner plus a technical friend or two. Creating a Supabase project,
filling `.env` and running `streamlit run ui_app.py` are acceptable prerequisites.
Nothing after that should need a terminal or a JSON editor.

**Success:** from "Supabase and `.env` ready" to "`python -m scoring.score_jobs` runs"
without opening a JSON file, for about 1–2 cents of LLM spend.

## Out of scope

- Supabase project creation, migrations and `.env` editing (documented in
  `docs/configuration.md`; the page only reports what is missing).
- Writing GitHub secrets. The page produces the value; the user pastes it.
- The tailor's fact base (`profile_facts.json`). It seeds itself from the CV and
  profile on first use; onboarding leaves it alone.
- Settings in `config.py` (search queries, thresholds).

## What it replaces

| Today | After |
|---|---|
| Upload `resume.pdf` to the `resumes` bucket in the Supabase dashboard | Upload button on the page |
| `python -m resume.resume_parser` (one Sonnet call) | Parsed inside the onboarding call (one Haiku call) |
| Hand-write `candidate_profile.json` from the example | Drafted from the CV + answers |
| Hand-write `application_answers.json` | Filled from the same answers |
| Paste the profile into `CANDIDATE_PROFILE_JSON` by hand | Copy button with a one-line JSON |

`python -m resume.resume_parser` keeps working for re-parsing from the command line
and in `parse_resume.yml`.

## Cost

Exactly **one LLM call per onboarding run**, on `ONBOARDING_MODEL` (new config
setting, default `config.LLM_SCREEN_MODEL`, i.e. Haiku). It sends the CV text once
and returns everything in one structured response. Answers are mapped to fields in
code; no second call. Re-opening the page to edit costs nothing — the call only runs
when a new CV is uploaded or the user presses *Re-read my CV* (which downloads the
stored PDF). The call's result is kept in `onboarding_draft.json` (gitignored, it
holds the parsed CV), so editing answers later reuses it instead of calling again.

The call goes through the existing `screen_client` with `model_override=ONBOARDING_MODEL`,
so rate limiting, retries and the daily budget apply unchanged.

**Trade-off accepted:** the parsed CV now comes from Haiku rather than Sonnet. The
tailor seeds its fact base from this parse. If quality drops, set
`ONBOARDING_MODEL` to the Sonnet model in `.env`.

## Flow

### 0. Status strip

At the top of the page, one chip per prerequisite, each green or red with the fix:

- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` set
- an LLM key set for `ONBOARDING_MODEL`'s provider
- database reachable (a `select` on `base_resume` with `limit 1` succeeds)
- CV parsed (a `base_resume` row exists)
- profile saved (`candidate_profile.json` exists and passes validation)

If the first three are not green, the upload is disabled and the strip says which
`.env` variable is missing. No LLM call is attempted.

### 1. Upload

`st.file_uploader` for one PDF. On upload:

1. Extract text locally with the existing `resume.resume_parser.extract_text_from_pdf`
   (pdfplumber, free). Empty text → error "This PDF has no text layer (scanned?)."
   and stop.
2. Store the PDF in the `resumes` bucket as `resume.pdf` (upsert), via a new
   `supabase_utils.upload_base_resume_pdf(bytes)`. A storage failure is a warning,
   not a stop: the parse can proceed without it.
3. Run the onboarding call (step 2).

If a `base_resume` row already exists, the page opens at step 3 with fields filled
from the existing files and the stored CV; uploading again is optional.

### 2. The onboarding call

Input: the CV text, today's date (via `scoring.availability.note()`), and the list
of **required fields** with one line each on what they mean.

Output, one Pydantic model `OnboardingDraft`:

- `resume: models.Resume` — the same shape `resume_parser` produces today. Saved to
  `base_resume` with `save_base_resume` and to `config.BASE_RESUME_PATH`, applying
  the same empty→`"NA"` normalisation `resume_parser.main` applies (moved into a
  shared helper).
- `roles: list[RoleKind]` — one per `resume.experience` entry, by index:
  `kind ∈ {full_time, working_student, internship, thesis_or_research}`, and
  `confident: bool`.
- `languages: list[{language, level, confident}]`, level as CEFR or "native".
- `location: {city, country, confident}`.
- `short_profile: str` — draft of the four-line summary the scorer reads.
- `skills: list[{skill, tier, reason}]` — tier 1–3 only (judged from the CV). Tiers
  4–5 come only from answers.
- `questions: list[Question]`, at most 12 (nine required fields can all be unknown):
  - `id`, `field` (one of the required field keys, or `role_kind:<index>`,
    `language_level:<language>`, `extra_skills`)
  - `text` — written from the CV ("Your Master's at TUM ends 03/2026 — can you start
    full-time from April 2026?")
  - `type ∈ {date, yes_no, choice, text}`, `options` for `choice`
  - `suggested` — a pre-filled answer when the CV suggests one

The prompt requires one question for every required field the CV does not settle,
and allows the remainder for ambiguities (a role whose kind is unclear, a language
with no level). It forbids questions whose answer is already stated in the CV.

**Required fields** (the keys the profile and answers files need):

| Key | Feeds |
|---|---|
| `earliest_start` (date) | `profile_v2` Availability; `eintrittstermin` |
| `contract_deadline` (date, optional) | `profile_v2` Availability |
| `permit_status` (text) | `profile_v2` Work authorization; `aufenthaltstitel` |
| `needs_sponsorship` (yes/no + reasoning) | `profile_v2` Work authorization |
| `authorized_countries` (text) | `profile_v2` Work authorization |
| `relocation` (text) | `profile_v2` Location; `relocation` |
| `remote_ok` (yes/no) | `profile_v2` Location |
| `salary_expectation` (text) | `gehaltsvorstellung` |
| `notice_period` (text) | `kuendigungsfrist` |
| `working_hours` (choice) | `arbeitszeit` |
| `extra_skills` (text, optional) | evidence index tier 4 |

Months of experience are **not** asked of the model. `onboarding/draft.py` computes
them from each experience entry's `start_date`/`end_date` (formats seen in parsed
CVs: `YYYY-MM`, `MM/YYYY`, `Mon YYYY`, `YYYY`, `Present`/`heute`/`NA`), sums by
`roles[i].kind`, and marks a role it cannot date as a question
(`role_months:<index>`, type text) — the one question type added in code, free.

### 3. Questions

All questions on one form (`st.form`), grouped: *About your CV* (role kinds,
language levels, unclear months), then *About you* (required fields). Every widget
is pre-filled with `suggested`, so a correct draft is a single submit.

Before the form is drawn, every required field that no model question covers gets
a **built-in fallback question** (fixed text per field, in code) added to the same
form, so nothing has to be asked twice. After submit, `onboarding/questions.py`
checks every required non-optional field has a value; a cleared one is named in an
error and the form stays open. No LLM call.

### 4. Review and save

- The draft profile and answers, rendered as editable fields (not raw JSON): the
  four profile sections, the experience ledger with its computed months, the skills
  with tiers (tier editable per row), and the answers.
- **Save** writes `candidate_profile.json` and `application_answers.json`:
  1. existing files are copied to `<name>.bak` first (`*.json.bak` is gitignored —
     the backups hold the same personal data);
  2. the profile dict is validated with the scorer's own rules — the three keys
     `short_profile`, `experience_ledger`, `profile_v2`, the four ledger integers,
     and `profile_v2.format(effective_fte_years=0, **ledger)` succeeding;
  3. only then are both files written.
- After saving: a one-line JSON of the profile in `st.code` (copyable) with the
  instruction "GitHub → Settings → Secrets and variables → Actions →
  `CANDIDATE_PROFILE_JSON`", and a note that the next scoring run uses it.

## Building the files (`onboarding/build.py`)

Pure functions, no I/O:

- `build_profile(draft, answers, months) -> dict` produces the same structure as
  `candidate_profile.json.example`: `short_profile`, `experience_ledger` (the four
  month keys), `profile_v2` with the sections *Availability*, *Work authorization*,
  *Experience ledger* (using the `{...}` placeholders exactly as the example does),
  *Languages*, *Location*, *Evidence index*.
- `build_answers(answers) -> dict` produces `application_answers.json`'s keys.
- **Brace escaping:** every user- or model-provided string placed into `profile_v2`
  has `{` → `{{` and `}` → `}}`, because the scorer calls `profile_v2.format(...)`.
  The placeholders the template itself needs are left single.
- `profile_from_existing(profile, answers) -> prefill` reads the current files back
  into form values so the page can be re-run for edits. A value it cannot find
  (a hand-written profile in another shape) is left empty and asked again through
  the fallback question; the original file survives as `.bak`.

## Layout

```
onboarding/
    __init__.py
    draft.py       the one LLM call, OnboardingDraft, month counting
    questions.py   required fields, fallback questions, completeness check
    build.py       draft + answers → the two files; validation; prefill from existing
    status.py      the status strip's checks (env vars, provider key, profile present)
ui_app.py          render_setup_page(): strip, upload, questions, review — rendering only
db/supabase_utils.py  + upload_base_resume_pdf(), + base_resume_exists()
resume/resume_parser.py  empty→"NA" normalisation moved to a shared function (behaviour unchanged)
config.py          + ONBOARDING_MODEL
```

Navigation: a *Set up* entry in a new last sidebar group. When
`candidate_profile.json` is missing and `CANDIDATE_PROFILE_JSON` is unset, the app
opens on *Set up* instead of the queue.

## Error handling

| Failure | Behaviour |
|---|---|
| Missing `.env` value | Strip shows it; upload disabled |
| PDF has no text | Error, nothing saved, no LLM call |
| Storage upload fails | Warning; parse continues |
| LLM call fails or returns invalid JSON | Error with the reason; form opens empty with the built-in fallback questions for every required field, so setup can finish by hand |
| `save_base_resume` fails | Warning; profile can still be saved (the scorer reads the CV from `base_resume`, so the strip stays red) |
| Validation fails on save | Nothing written; the failing field is named |

## Testing

All credential-free, LLM and Supabase faked, like the existing suite.

- `test_onboarding_draft.py`: month counting across the date formats, open-ended
  roles, undatable roles becoming questions; draft parsing from a canned model
  response.
- `test_onboarding_questions.py`: completeness check, fallback questions for skipped
  fields, optional fields not forced.
- `test_onboarding_build.py`: built profile passes the scorer's loader
  (`scoring.score_jobs._load_candidate_profile` against a temp file); brace escaping
  with `{`/`}` in answers; answers file keys; round trip existing → prefill → build.
- `test_ui_app.py`: the *Set up* page renders; with no profile the app opens on it;
  a faked upload → questions → save writes both files to a temp dir; LLM failure
  leaves a usable form.

## Docs

README quick start steps 4–5 collapse into "open the app → *Set up*". The
configuration doc gains `ONBOARDING_MODEL` and keeps the manual route as a fallback.
