# Job Scraper

An automated job pipeline for the German market: it finds postings, scores each
one against your CV with an LLM, ranks them, and gives you a keyboard-driven
queue to work through. Built for volume — the goal is applications sent per
week, not a prettier database.

Four times a day, unattended, it:

```
scrape  →  dedup  →  screen (cheap LLM)  →  score (full LLM)  →  rank  →  alert
LinkedIn DE                 hard gates          0-100 + breakdown      email
Arbeitsagentur              + rough band                               if 70+
```

Everything lands in Supabase. You then open the Streamlit app and work the
queue: read the verdict, open the posting, mark applied or skip with a reason.

**Docs:** [Features](docs/features.md) · [Configuration](docs/configuration.md) ·
[CV tailoring](tailor/README.md) · [CV archetypes](clustering/README.md)

---

## Quick start

You need Python 3.11+, a [Supabase](https://supabase.com) project (the free tier
is enough) and an API key for one LLM provider (Anthropic by default). Run every
command from the repository root.

**1. Install**

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**2. Add your credentials**

```bash
cp .env.example .env
```

Fill in `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` and your LLM key.
Using a provider other than Anthropic? See
[Switching LLM provider](docs/configuration.md#switching-llm-provider).

**3. Create the database**

In the Supabase SQL editor, run `supabase_setup/init.sql`, then each
`supabase_setup/add_*.sql` migration and `raise_customization_threshold.sql`.
The order and what each one does are in
[Database](docs/configuration.md#database-supabase).

**4. Add your CV**

Upload your CV as a PDF to the `resumes` bucket in Supabase Storage, then:

```bash
python -m resume.resume_parser
```

**5. Describe yourself**

```bash
cp candidate_profile.json.example candidate_profile.json
cp application_answers.json.example application_answers.json
```

Fill in both. The profile holds what your CV does not say (start date, work
permit, experience by kind) and the scorer will not run without it. The answers
fill the application packs. Both are gitignored. See
[Your personal files](docs/configuration.md#your-personal-files).

**6. Choose what to search for**

Edit the search queries and location in [`config.py`](config.py)
(section 2, *User preferences*). The defaults search for data / ML / AI roles in
Germany.

**7. Run it**

```bash
python -m sources.scraper          # find jobs   (--source linkedin | arbeitsagentur)
python -m scoring.score_jobs       # screen + score
streamlit run ui_app.py            # work the queue
```

To run it unattended four times a day, push the repository to GitHub and add your
secrets: see [GitHub Actions](docs/configuration.md#github-actions).

---

## Commands

| Command | What it does |
|---|---|
| `python -m sources.scraper` | Scrape all sources (`--source <name>` for one) |
| `python -m scoring.score_jobs` | Screen and score new jobs, then send the alert mail |
| `streamlit run ui_app.py` | The app: apply queue, applications, calibration, CVs |
| `python -m maintenance.job_manager` | Housekeeping: expire, mark closed, delete old |
| `python -m resume.resume_parser` | Re-parse your CV after uploading a new one |
| `python -m scoring.notify --test` | Send a test alert mail |
| `python -m clustering.run` | Group postings into CV archetypes |
| `python -m clustering.cv_fit` | Compare your CV against each archetype |
| `python -m maintenance.check_scoring_health` | Is the scorer still producing the fields calibration needs? |
| `python -m maintenance.dedup_existing` | Collapse duplicates already stored (dry run; `--apply` to write) |
| `python -m maintenance.rescore_degraded` | Re-score rows missing calibration fields |
| `python -m maintenance.mark_applied <job_id>` | Mark applied without opening the app |

## Tests

```bash
python -m pytest tests/ -q
```

No credentials needed — every external call is faked, including the Streamlit
UI, which is rendered headlessly.

---

## Project structure

Eight packages, each answering one question. Only three Python files sit at the
root, and each is there for a reason.

```
config.py          the file you edit: search queries, caps, thresholds (no secrets — it is committed)
models.py          the shared Pydantic schemas; both the CV side and the scoring side speak them
ui_app.py          the Streamlit entry point, so `streamlit run ui_app.py` needs no path juggling

*.json.example     templates for your personal files (copy without .example; the copies are gitignored)
.env.example       template for your credentials
docs/              features tour and the full configuration reference

sources/           where jobs come from
    scraper.py         LinkedIn + the per-source runners behind `--source`
    arbeitsagentur.py  Bundesagentur für Arbeit Jobsuche API
    dedup.py           canonical job identity across sources
    role_type.py       tags graduate / trainee programmes by title
    scrape_guard.py    per-source accounting; fails a run that fetched nothing
    user_agents.py     user-agent pool

scoring/           posting → ranked, explained score
    score_jobs.py      the screening pass and the full scoring pass
    llm_client.py      LiteLLM wrapper: rate limits, retries, daily budget
    availability.py    today's date and your start date, in the form prompts need
    manual_jobs.py     jobs you added by hand, scored like the rest
    notify.py          email alert when a run turns up a strong match

resume/            your CV
    resume_parser.py             PDF → structured data
    custom_resume_generator.py   older per-job tailoring (not scheduled; Write my CV replaces it)
    pdf_generator.py             ReportLab layout (parked — nothing calls it yet)

tailor/            one posting → a CV and cover letter (see tailor/README.md)
    facts.py           the fact base: what is true about you, atomised and tiered
    harvest.py         facts the scorer already noticed, offered for confirmation
    interview.py       asks about gaps the posting needs and the base cannot answer
    writer.py          composes CV + Anschreiben, every line citing facts
    verify.py          deterministic honesty checks — citations, numbers, phrasing
    judge.py           the hiring manager: objections, never a score
    loop.py            write → verify → judge → revise, and when to stop
    documents.py       the document shapes, and rendering them to text
    store.py           saved applications, and the non-claim personal details
    settings.py        models and loop limits

clustering/        postings → a few CV archetypes (see clustering/README.md)
    corpus.py          gates the scored jobs down to the ones worth a CV
    schema.py          the closed vocabulary a posting is normalised into
    extract.py         one cheap LLM call per posting, cached by job_id
    features.py        blocked, weighted, rarity-scaled feature space
    cluster.py         PCA + k-means, with bootstrap stability and per-job margins
    report.py          centroids read back as shares and lift over the corpus
    cv_fit.py          scores your CV against each archetype: what is there, what is not
    results.py         loads a finished run for the Streamlit page
    settings.py        thresholds and worker count
    run.py             `python -m clustering.run`

review/            everything behind the Streamlit app
    apply_queue.py       ordering, cursor, date windows, skip reasons
    job_view.py          a score breakdown → the few lines worth reading
    application_pack.py  assembles one application's folder
    application_view.py  the "Where I applied" records
    calibration.py       is the scorer predictive? (Brier, interview rate)
    market.py            what the market asks for
    theme.py             palette, type and HTML fragments for the app
    dashboard.py         the static HTML dashboard

db/                all Supabase access — nothing else talks to the database
    supabase_utils.py

maintenance/       standalone commands over the stored corpus
    job_manager.py, dedup_existing.py, rescore_existing.py, rescore_degraded.py,
    check_scoring_health.py, mark_applied.py, purge_low_scores.py, purge_freelance.py

supabase_setup/    schema + idempotent migrations
.github/workflows/ the scheduled pipeline and one-off jobs
tests/             credential-free test suite
```

Generated at run time and gitignored: `output/` (application packs, dedup
backups), `dashboard.html`, `tailor/cache/`, `clustering/cache/cv_profile.json`.

Modules are run as `python -m <package>.<module>` from the repository root, which
is also what the workflows do.

## Licence

MIT — see [LICENSE](LICENSE).

## Acknowledgements

[LiteLLM](https://docs.litellm.ai/) for provider-agnostic LLM calls,
[Supabase](https://supabase.com/) for storage,
[Streamlit](https://streamlit.io/) for the UI,
[Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) and
[pdfplumber](https://github.com/jsvine/pdfplumber) for parsing.

## Disclaimer

For personal use. Scraping LinkedIn may be against their Terms of Service — use
this responsibly and at your own risk.
