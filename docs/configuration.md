# Configuration

Every setting the project reads, where it lives, and when you would change it.
If you are setting up for the first time, follow the [Quick start](../README.md#quick-start)
first and come back here for details.

## Where settings live

| What | Where | Committed? |
|---|---|---|
| Secrets: database, LLM and SMTP credentials | `.env` (copy from [`.env.example`](../.env.example)) | No — gitignored |
| Search queries, caps, thresholds, models | [`config.py`](../config.py) | **Yes** — never put a secret here |
| Your situation: permit, availability, experience | `candidate_profile.json` | No — gitignored |
| Answers German application forms ask for | `application_answers.json` | No — gitignored |
| Jobs you found yourself | `manual_jobs.json` | No — optional |
| Facts about you for the CV tailor | `profile_facts.json` | No — gitignored, built by the app |
| The Set up page's last CV read | `onboarding_draft.json` | No — gitignored |
| Your pre-made CV files | `cv/` | No — gitignored |
| The same secrets, for the scheduled runs | GitHub repository secrets and variables | — |

Every command runs from the repository root, and every path above is relative to it.

---

## Environment variables (`.env`)

### Required

| Variable | What it is |
|---|---|
| `SUPABASE_URL` | Project URL, from Supabase → Project Settings → API |
| `SUPABASE_SERVICE_ROLE_KEY` | The `service_role` key from the same page. It bypasses row-level security, so keep it out of anything public |
| One LLM key | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` or `GROQ_API_KEY` — whichever provider your models use |

The default models are Anthropic's, so the default setup needs `ANTHROPIC_API_KEY`.
To use another provider, set its key and point the models at it — see
[Switching LLM provider](#switching-llm-provider).

`LLM_API_KEY` also works as a generic key: it is copied into the right
provider variable when its format matches the model's provider.

### Optional

| Variable | Default | What it does |
|---|---|---|
| `LLM_MODEL` | `anthropic/claude-sonnet-4-6` | Model for full scoring and CV tailoring |
| `LLM_SCREEN_MODEL` | `anthropic/claude-haiku-4-5` | Cheap model for the screening pass |
| `ONBOARDING_MODEL` | `LLM_SCREEN_MODEL` | Model for the Set up page's single CV read. Set it to `LLM_MODEL`'s value if the parsed CV comes back thin |
| `LLM_DEBUG` | off | Verbose LLM logging |
| `CANDIDATE_PROFILE_JSON` | unset | The whole candidate profile as a JSON string. Used instead of `candidate_profile.json` when set — this is how CI gets it |
| `TAILOR_FACTS_JSON` | unset | The fact base as a JSON string, for CI. Unset, jobs are scored against the CV alone |
| `JOBS_TO_SCREEN_PER_RUN` | 40 | Jobs screened per scoring run |
| `JOBS_TO_SCORE_PER_RUN` | 15 | Jobs fully scored per run |
| `LINKEDIN_MAX_JOBS_PER_SEARCH` | 10 | Jobs kept per LinkedIn query |
| `ARBEITSAGENTUR_MAX_JOBS_PER_SEARCH` | 25 | Jobs kept per Arbeitsagentur query |
| `ARBEITSAGENTUR_PUBLISHED_SINCE_DAYS` | 1 | Arbeitsagentur search window, in days |
| `LINKEDIN_MAX_START` | 10 | Last LinkedIn results offset (0 = first page only). Lower it if LinkedIn starts blocking |
| `RESCORE_WITH_CUSTOM_RESUME` | off | Also score each tailored CV (recorded beside the real score, never in place of it) |
| `PURGE_MIN_SCORE` / `PURGE_LIMIT` | 20 / 400 | Housekeeping: delete jobs scored below this, at most this many per run |

The per-run caps exist as environment variables so a one-off backfill can raise
them for a single run without editing the committed defaults.

Email alert variables are listed under [Email alerts](#email-alerts). The
tailoring and clustering packages have their own, listed in
[tailor/README.md](../tailor/README.md#configuration) and
[clustering/README.md](../clustering/README.md).

---

## Your personal files

The **Set up** page in the app writes `candidate_profile.json` and
`application_answers.json` for you from your CV and a few answers, and keeps the
previous versions as `.bak`. The manual route below still works.

Each has a committed `.example` next to it. Copy it and fill it in:

```bash
cp candidate_profile.json.example candidate_profile.json
cp application_answers.json.example application_answers.json
cp manual_jobs.json.example manual_jobs.json      # optional
```

- **`candidate_profile.json`** — read by the scorer on every job. It holds what the
  CV does not say: when you can start, your work permit, months of experience by
  kind, languages, location, and an evidence index (how provable each skill is).
  The scorer refuses to run without it. Be honest here; the score is only as good
  as this file.
- **`application_answers.json`** — Gehaltsvorstellung, earliest start, notice
  period, permit status. Copied into each application pack. Not used for scoring.
- **`manual_jobs.json`** — a list of postings you found yourself; they are scored
  like scraped ones on the next scoring run.
- **`profile_facts.json`** — created and grown by the *Write my CV* screen as it
  asks you questions. You do not write it by hand.
- **`cv/`** — your finished CV files, if you keep more than one. Tell
  `config.py` which to use per job title:

  ```python
  CV_KEYWORD_ROUTES = [("data engineer", "cv_data_engineering.pdf"), ("data", "cv_data_science.pdf")]
  CV_DEFAULT = "cv_general.pdf"
  ```

  First match wins, so list specific keywords first. Leave both empty and the
  application pack asks you to pick.

---

## `config.py`

The file is split into three sections:

1. **Core system configuration** — table and bucket names. Leave alone.
2. **User preferences** — what you are expected to change:
   - `LINKEDIN_SEARCH_QUERIES` and `ARBEITSAGENTUR_SEARCH_QUERIES` — the job titles
     to search for. German terms only help when they are what employers actually
     type; the comments record which were measured to return nothing.
   - `GRADUATE_PROGRAM_QUERIES_EN` / `_DE` — trainee and graduate programme searches.
     Empty both lists if you do not want programmes.
   - `LINKEDIN_LOCATION`, `LINKEDIN_GEO_ID`, `ARBEITSAGENTUR_LOCATION` — where to search.
   - `LINKEDIN_F_E` (experience level), `LINKEDIN_F_WT` (on-site/remote/hybrid),
     `LINKEDIN_JOB_TYPE` — LinkedIn filters, explained inline.
   - `SCRAPING_SOURCES` — which sources run.
   - `SCORE_LAST_PROVIDERS` — sources scored only after all others.
   - `RESUME_CUSTOMIZATION_MIN_SCORE` — the queue suggests a tailored CV at or
     above this score. Tailoring itself only runs when you start it on *Write my CV*.
   - `CV_LIBRARY_DIR`, `CV_KEYWORD_ROUTES`, `CV_DEFAULT` — see above.
3. **Advanced system settings** — rate limits, retries, expiry windows. They are
   calibrated to avoid being blocked; change them only for a reason.

---

## Database (Supabase)

1. Create a project at [supabase.com](https://supabase.com). The free tier is enough.
2. In the SQL editor, run [`supabase_setup/init.sql`](../supabase_setup/init.sql).
   It creates the `jobs`, `customized_resumes` and `base_resume` tables and the
   `resumes` and `personalized_resumes` storage buckets.
3. Run each migration below, in this order. All are idempotent — re-running one
   is always safe, and it is the fix if a column is reported missing.

   | Migration | Adds |
   |---|---|
   | `add_score_breakdown.sql` | Full LLM breakdown alongside the numeric score |
   | `add_why_me_pitch.sql` | Pitch column (no longer generated; older rows still have it) |
   | `add_application_outcomes.sql` | Interview / rejection / offer tracking |
   | `add_dismissal.sql` | Skip, with a reason |
   | `add_deleted_jobs.sql` | Hard delete, with a tombstone so a job stays deleted |
   | `add_alt_sources.sql` | Cross-source dedup |
   | `add_program_type.sql` | Graduate / trainee programme tag |
   | `raise_customization_threshold.sql` | Tailoring picks only jobs scored 70+ at the database level |

4. Upload your CV on the app's **Set up** page — it stores and parses it. To do it
   by hand instead, upload the PDF to the `resumes` storage bucket as `resume.pdf`, then:

   ```bash
   python -m resume.resume_parser
   ```

   Repeat this whenever you upload a new CV (on GitHub: run `parse_resume.yml`).

---

## Switching LLM provider

Any model [LiteLLM supports](https://docs.litellm.ai/docs/providers) works. Set the
provider's key and both models, for example in `.env`:

```
OPENAI_API_KEY=sk-...
LLM_MODEL=openai/gpt-4o
LLM_SCREEN_MODEL=openai/gpt-4o-mini
```

On GitHub Actions the workflows pass `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GROQ_API_KEY` and `LLM_API_KEY` through; to change models there, edit the
defaults in `config.py`. The CV tailor's judge model is set separately
(`TAILOR_JUDGE_MODEL`).

---

## Email alerts

Off by default. When enabled, the scoring run sends one mail at the end listing
the jobs *that run* scored at or above `EMAIL_ALERT_MIN_SCORE` (default 70).
English-language ads have a lower bar, `EMAIL_ALERT_MIN_SCORE_ENGLISH` (default
55, never above the general one), because both interviews so far came from
English ads scored 58. Below the general bar a job recommended *skip* is never
mailed. Set the English value equal to the general one to turn the lower bar
off. A run with nothing above the bar sends nothing. A job is scored once, so no
job is ever alerted twice, and an unreachable mail server is logged rather than
failing the run.

Any SMTP provider works. For Gmail, turn on 2-Step Verification and create an
[App Password](https://myaccount.google.com/apppasswords) — the account password
is always refused.

```
EMAIL_ALERTS_ENABLED=true
EMAIL_ALERT_MIN_SCORE=70
EMAIL_ALERT_MIN_SCORE_ENGLISH=55   # English-language ads; set to 70 to turn off
EMAIL_ALERT_MAX_JOBS=10            # jobs listed in full before falling back to a count
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587                      # 465 for implicit TLS; anything else uses STARTTLS
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your_app_password
EMAIL_FROM=you@gmail.com           # defaults to SMTP_USER
EMAIL_TO=you@gmail.com             # comma-separated for several recipients
```

Check it before trusting a scheduled run:

```bash
python -m scoring.notify --test
```

---

## GitHub Actions

The scheduled pipeline runs on GitHub Actions. Fork or push the repository, enable
Actions, and add the values below under **Settings → Secrets and variables → Actions**.
`run_all.yml` then runs the whole pipeline four times a day.

**Secrets**

| Secret | Required | Notes |
|---|---|---|
| `SUPABASE_URL` | Yes | |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | |
| `ANTHROPIC_API_KEY` | For the default models | Or `OPENAI_API_KEY`, `GROQ_API_KEY`, `LLM_API_KEY`, `GEMINI_FIRST_API_KEY` |
| `CANDIDATE_PROFILE_JSON` | Yes | The full contents of your `candidate_profile.json` |
| `TAILOR_FACTS_JSON` | No | The full contents of `profile_facts.json` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO` | For email alerts | |

**Variables** (not secret; all optional)

| Variable | Notes |
|---|---|
| `EMAIL_ALERTS_ENABLED` | `true` to turn on alerts |
| `EMAIL_ALERT_MIN_SCORE`, `EMAIL_ALERT_MIN_SCORE_ENGLISH` | Alert thresholds |
| `PURGE_MIN_SCORE`, `PURGE_LIMIT` | Housekeeping limits |

**Workflows**

| Workflow | What it does |
|---|---|
| `run_all.yml` | The whole pipeline, 4×/day: scrape (one runner per source, in parallel) → score → housekeeping → dashboard |
| `scrape_jobs.yml` / `score_jobs.yml` / `job_manager.yml` | The individual stages, for running one by hand |
| `parse_resume.yml` | Re-parse your CV after you upload a new one |
| `backfill.yml` | Widen the date window for one source to catch up |
| `rescore_existing.yml` / `rescore_degraded.yml` | Re-score stored jobs after a scorer change |
| `dashboard.yml` | Rebuild the static dashboard |

Runs never overlap, and a failed scrape leg does not stop scoring — whatever
landed still deserves to be looked at.

> **This repository may be public.** Never commit `.env`, your personal JSON files,
> `cv/`, `output/` or `dashboard.html`. All are in `.gitignore`; keep them there.
