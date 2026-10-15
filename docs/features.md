# Features

A tour of what the pipeline and the app do, with links to the code behind each part.
For setup, see the [README](../README.md); for every setting, see [configuration.md](configuration.md).

### Finding jobs

- **Two sources.** LinkedIn (Germany) and the Bundesagentur für Arbeit Jobsuche
  API — the second is free for employers to post to, which is why it carries the
  Mittelstand that never reaches LinkedIn. ([sources/scraper.py](../sources/scraper.py),
  [sources/arbeitsagentur.py](../sources/arbeitsagentur.py))
- **Cross-source dedup.** The same opening arrives as "YPOG GmbH / AI/ML Engineer
  (m/w/d)" from one source and "YPOG / AI/ML Engineer" from another. Company and
  title are normalised so it stays one row, and the employer-nearest URL wins —
  applying direct beats applying through an aggregator. ([sources/dedup.py](../sources/dedup.py))
- **A source can't die quietly.** Every run accounts for each posting it fetched:
  already stored, filtered (with the reason), or saved. A source that returns
  nothing at all fails the run instead of showing green. ([sources/scrape_guard.py](../sources/scrape_guard.py))
- **Manual jobs.** Drop a posting you found yourself into `manual_jobs.json` and
  it gets scored like any other. ([scoring/manual_jobs.py](../scoring/manual_jobs.py))
- **Graduate and trainee programmes.** Structured intakes (Traineeprogramm,
  graduate programme, AI residency) are searched for by name in both languages,
  tagged from the title at scrape time, and scored as what they are: the intake
  date is checked against your availability, eligibility windows ("max. 2 Jahre
  Berufserfahrung") become a gate, and your experience counts as differentiation
  in a pool of fresh graduates rather than as a seniority gap. Arbeitsagentur
  files half of them under its Praktikum/Trainee category, which used to be
  dropped wholesale; a programme there is now kept while a Praktikum is not.
  The queue can show programmes only, roles only, or both.
  ([sources/role_type.py](../sources/role_type.py))

### Scoring

- **Two-stage scoring, so the spend goes where it matters.** A cheap model
  screens every new job for hard gates and a rough band; only what passes gets a
  full scoring call. Failures are stored with a capped score and never looked at
  again. ([scoring/score_jobs.py](../scoring/score_jobs.py))
- **A breakdown, not just a number.** Each job gets 0–100 plus what to lead with,
  what they'll push back on, what to fix before applying, estimated hours of
  effort, interview odds, and a recommendation. ([review/job_view.py](../review/job_view.py))
- **Interview odds are graded on a curve.** The weakest slice is downgraded
  relative to the run plus the few hundred most recently scored jobs, because an
  absolute floor fired on every job ever scored and nothing could reach "apply
  now" — and a single four-times-a-day run is too small to be its own curve.
- **Any LLM provider.** Gemini, OpenAI, Anthropic, Groq, Ollama and ~400 more
  through LiteLLM, with rate limiting, backoff and a daily request budget.
  ([scoring/llm_client.py](../scoring/llm_client.py))

### Working the queue — `streamlit run ui_app.py`

Five screens, grouped in the sidebar by how often you open them: *Jobs to
apply* and *Write my CV* every day, *Where I applied* every week, *Is the score
right?* and *Which CV to use* every month. The look — palette, type, the pill
controls and surface cards — lives in [review/theme.py](../review/theme.py) and
[.streamlit/config.toml](../.streamlit/config.toml); the pages compose HTML
fragments from there rather than styling inline.

- **Jobs to apply.** Every card leads with the verdict: the score as a disc
  with its band ("Strong", "Worth it", "Marginal", "Long shot" — set against
  the observed distribution, not a school scale) and its place in the corpus,
  then the one-line verdict and the gates as chips, German always first. Sort
  by best match (English-language ads first, the strongest predictor of an
  interview so far), least effort or newest; a strip under the controls says what
  the filters are hiding ("Older than 24 hours · 194", "Score under 70 · 12")
  and each chip drops that filter with one click, so a short queue never reads
  as an empty market.
- **One at a time.** The default view: one job, driven from the keyboard —
  `a` applied, `s` skip, `o` open the posting, `p` build the application pack,
  `c` tailor a CV for it, `j`/`k` to move — with the pitch, the context and the
  key legend in a side rail. The cursor is anchored to a job, not a position,
  so it survives the queue refreshing underneath you.
  ([review/apply_queue.py](../review/apply_queue.py))
- **Skips carry a reason** — asked at the moment of the decision, as chips
  (`1`–`9` from the keyboard) — because "I skipped every job needing C1" is a
  finding, not bookkeeping. One-step undo, and the row is never deleted.
- **Found timestamps.** Under 24 hours old a job shows the clock time and how
  long ago; past that, just the date. Being early to a posting is most of the
  advantage.
- **Application packs.** One button writes a folder with the answers every German
  form asks for (Gehaltsvorstellung, earliest start, permit status, notice
  period), a checklist, the pitch, and the right CV. No LLM, no generation — it
  collects what already exists. ([review/application_pack.py](../review/application_pack.py))
- **Where I applied.** Each application is a record, not a form: stage as a
  timeline, how long it has been quiet, what you led with and what they pushed
  back on. Tabs split open from needs-chasing from resolved; stage, reason and
  notes are edited behind an *Update* button. Applications silent for 30+ days
  are offered for closing out, never closed automatically.
  ([review/application_view.py](../review/application_view.py))
- **Is the score right?** Leads with the answer — "+7pt overconfident: it
  promises 31% and delivers 24%" — then interview rate by score band and the
  blockers: rejection reasons and your own skip reasons on one chart, because
  the two together are the real filter. Unresolved applications are excluded —
  you haven't heard back yet, which is not the same as a no.
  ([review/calibration.py](../review/calibration.py))
- **Which CV to use.** The postings worth applying to, grouped into a handful
  of role archetypes — one base CV each, instead of one generic CV for
  everything. Per archetype: how many postings, the best score, the skills to
  lead with ranked by how over-represented they are, what the roles actually
  are, and the covered jobs. Reads the artefacts written by
  `python -m clustering.run`; the page never clusters or calls an LLM itself.
  ([clustering/](../clustering/))
- **Your CV against each archetype.** `python -m clustering.cv_fit` maps your CV
  onto the same skill vocabulary as the postings, then reports per archetype what
  you cover, what is true of you but missing from the CV, and what is genuinely
  absent — each gap weighted by how many postings actually ask for it.
  ([clustering/cv_fit.py](../clustering/cv_fit.py))
- **Write my CV.** Reachable from any job in the queue via **Tailor a CV for
  this** in the overflow menu (or `c`). Three steps with their state on a bar —
  fill the gaps, write and argue, read and send. Pick one posting and get a tailored CV and Anschreiben,
  written only from a fact base about you — every line cites the fact it rests
  on, so nothing can be invented — then argued over by a simulated hiring manager
  until the objections stop being new. Asks you about gaps first, and keeps the
  answers. ([tailor/](../tailor/))

### Staying on top of it

- **Email alerts.** One mail at the end of a run listing the jobs that run scored
  at or above your threshold. Nothing clears the bar, no mail. Off by default —
  see [Email alerts](configuration.md#email-alerts). ([scoring/notify.py](../scoring/notify.py))
- **Housekeeping.** Old postings expire, closed ones are marked removed, and
  long-dead rows are deleted. ([maintenance/job_manager.py](../maintenance/job_manager.py))
- **A static dashboard** is published as a workflow artifact if you want a
  read-only view without running Streamlit. ([review/dashboard.py](../review/dashboard.py))
- **Tailoring is suggested, never automatic.** A job scored at or above
  `RESUME_CUSTOMIZATION_MIN_SCORE` carries a *CV · worth tailoring* chip, and the
  one-at-a-time view offers **Write a tailored CV**, which opens it on *Write my
  CV*. Nothing is generated until you start it there; a job you have tailored
  for shows *CV · tailored* instead.
