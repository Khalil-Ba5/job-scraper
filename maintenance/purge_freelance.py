"""Delete freelance and contract postings already in the corpus.

Run it with ``python -m maintenance.purge_freelance``. The scrapers now refuse
these at the door (sources/scraper.py: is_freelance_role reads the description as
well as the title), so this clears what arrived before that, and anything a later
change to the pattern newly recognises.

Same three rules as maintenance.purge_low_scores, for the same reasons: only rows
nobody acted on (status 'new', no application, no dismissal), a tombstone for
every delete so the posting is not re-scraped and re-scored, and a cap per run.
"""

import argparse
import json
import logging
from typing import Any, Dict, List

import config
from db import supabase_utils
from sources.scraper import is_freelance_role

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DEFAULT_LIMIT = config._int_env("PURGE_LIMIT", 400)
REASON = "freelance"
_COLUMNS = ("job_id, job_title, company, location, level, description, resume_score, "
            "score_breakdown, dismissed_at")


def find_freelance(limit: int) -> List[Dict[str, Any]]:
    """Untouched postings whose title, level or description says freelance."""
    found, offset, page = [], 0, 1000
    try:
        while len(found) < limit:
            rows = (
                supabase_utils.supabase.table(config.SUPABASE_TABLE_NAME)
                .select(_COLUMNS)
                .eq("status", "new")
                .is_("application_date", None)
                .range(offset, offset + page - 1)
                .execute()
            ).data or []
            found += [r for r in rows
                      if not r.get("dismissed_at")
                      and is_freelance_role(r.get("job_title"), r.get("level"), r.get("description"))]
            if len(rows) < page:
                break
            offset += page
    except Exception as exc:  # noqa: BLE001
        logging.error(f"Could not list freelance jobs: {exc}")
    return found[:limit]


def purge(limit: int = DEFAULT_LIMIT, dry_run: bool = False) -> Dict[str, int]:
    rows = find_freelance(limit)
    if not rows:
        logging.info("No freelance postings to remove.")
        return {"found": 0, "deleted": 0, "failed": 0}

    logging.info("Removing %d freelance posting(s)%s.", len(rows),
                 " — DRY RUN, nothing will be deleted" if dry_run else "")
    deleted = failed = 0
    for row in rows:
        label = f"{row.get('job_title')} @ {row.get('company')} ({row.get('resume_score')})"
        if dry_run:
            logging.info(f"  would delete: {label}")
            continue
        if supabase_utils.delete_job(row, REASON, note="auto-removed: freelance/contract"):
            deleted += 1
            logging.info(f"  deleted: {label}")
        else:
            failed += 1
            logging.warning(f"  failed to delete: {label}")

    logging.info(f"Freelance purge finished: {deleted} deleted, {failed} failed.")
    return {"found": len(rows), "deleted": deleted, "failed": failed}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete freelance/contract postings.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"Most postings to delete in one run (default {DEFAULT_LIMIT}).")
    parser.add_argument("--dry-run", action="store_true",
                        help="List what would go without deleting anything.")
    args = parser.parse_args(argv)
    counts = purge(args.limit, args.dry_run)
    print(json.dumps(counts))
    return 0 if not counts["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
