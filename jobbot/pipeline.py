"""One run: search -> read -> score -> prepare documents -> fill (and, only when allowed, submit) -> report."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from jobbot import notify, reports
from jobbot.config import auto_submit_allowed, load_profile, paths
from jobbot.db import DB, DUBAI, now_iso
from jobbot.documents import generate_application_documents
from jobbot.extractor import extract
from jobbot.indeed.browser import BrowserSession, PauseRequired, is_signed_in
from jobbot.sanitize import injection_flags, strip_injections
from jobbot.scorer import candidate_years_from_profile, score
from jobbot.screening import Answerer

log = logging.getLogger("jobbot.pipeline")

APPLY_QUEUE_STATUSES = ("shortlisted", "prepared")
CATEGORY_ORDER = ("medical_coding", "medical_insurance", "billing_rcm")


@dataclass
class RunStats:
    run_id: int = 0
    mode: str = "review"
    found: int = 0
    new_jobs: int = 0
    relevant: int = 0
    prepared: int = 0
    ready_for_review: int = 0
    submitted: int = 0
    needs_attention: int = 0
    external: int = 0
    rejected: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    paused: str | None = None
    touched_job_ids: list[int] = field(default_factory=list)
    auto_reason: str = ""


class RunLock:
    def __init__(self, path: Path, stale_hours: float = 4):
        self.path, self.stale = path, stale_hours * 3600

    def __enter__(self):
        if self.path.exists() and time.time() - self.path.stat().st_mtime < self.stale:
            raise RuntimeError(f"Another run is in progress (lock file {self.path}).")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(os.getpid()))
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def is_scheduled_day(settings: dict, when: datetime | None = None) -> bool:
    when = when or datetime.now(DUBAI)
    days = [d[:3].title() for d in settings.get("schedule", {}).get("days", [])]
    return when.astimezone(DUBAI).strftime("%a") in days


def search_plan(settings: dict) -> list[tuple[str, str, str]]:
    titles = settings.get("job_titles", {})
    plan = []
    for cat in CATEGORY_ORDER + tuple(k for k in titles if k not in CATEGORY_ORDER):
        for t in titles.get(cat, []):
            for loc in settings.get("locations", []):
                plan.append((cat, t, loc))
    return plan[: settings.get("max_searches_per_run", 24)]


# ---------------- scoring ----------------
def evaluate_job(db: DB, job_id: int, settings: dict, profile: dict, stats: RunStats | None = None) -> dict:
    job = db.get_job(job_id)
    description, removed = strip_injections(job.get("description") or "")
    req = extract(job.get("title"), job.get("company"), job.get("location"), description, job.get("salary") or "")
    sc = score(req, candidate_years=candidate_years_from_profile(profile),
               allowed_locations=settings.get("locations", []),
               strict_locations=settings.get("only_apply_in_search_locations", True),
               minimum_salary_aed=int(settings.get("minimum_salary_aed") or 0))
    flags = list(req.flags)
    inj = injection_flags(job.get("description") or "")
    if inj or removed:
        flags.append("Listing contains text aimed at automated tools; it was ignored and this job is never auto-submitted")
    if sc.reject_reason:
        status = "rejected"
    elif sc.total >= settings["match_threshold"]:
        status = "shortlisted"
    elif sc.total >= settings["review_threshold"]:
        status = "possible"
    else:
        status = "rejected"
    dup = db.already_applied(job.get("company"), job.get("title"), exclude_id=job_id)
    reject_reason = sc.reject_reason or ("Score below review threshold" if status == "rejected" else None)
    if dup and status in ("shortlisted", "possible"):
        status, reject_reason = "rejected", f"Duplicate of job #{dup['id']} (same company and title, {dup['status']})"
    db.update_job(job_id, score=sc.total, classification=sc.classification, score_breakdown=sc.breakdown,
                  extracted=req.to_dict(), flags=flags, category=req.category,
                  salary_min_aed=req.salary_min_aed, reject_reason=reject_reason)
    db.set_status(job_id, status, f"score {sc.total}: {sc.classification}", stats.run_id if stats else None)
    if stats:
        if status in ("shortlisted", "possible"):
            stats.relevant += 1
        else:
            stats.rejected.append({"id": job_id, "title": job.get("title"), "company": job.get("company"),
                                   "url": job.get("url"), "score": sc.total, "reason": reject_reason})
    return {"status": status, "score": sc.total, "requirements": req, "score_obj": sc}


# ---------------- discovery ----------------
def discover_with_browser(session: BrowserSession, db: DB, settings: dict, profile: dict, stats: RunStats) -> None:
    from jobbot.indeed.search import read_job, search
    session.goto(session.base_url + "/")
    if not is_signed_in(session.page):
        raise PauseRequired("login", session.page.url, "Indeed session is signed out")
    budget = int(settings.get("max_job_pages_per_run", 60))
    for cat, title, loc in search_plan(settings):
        try:
            cards = search(session, title, loc, int(settings.get("posted_within_days", 7)),
                           int(settings.get("max_result_pages_per_search", 1)))
        except PauseRequired:
            raise
        except Exception as e:  # one broken search must not end the run
            stats.errors.append(f"Search '{title}' in {loc} failed: {e}")
            log.exception("search failed")
            continue
        stats.found += len(cards)
        for card in cards:
            if db.find_duplicate(job_key=card["job_key"], url=card["url"]):
                continue
            if db.find_duplicate(company=card.get("company"), title=card.get("title")):
                continue  # same company + title already known (often re-posted)
            if budget <= 0:
                break
            try:
                detail = read_job(session, card["url"])
                budget -= 1
            except PauseRequired:
                raise
            except Exception as e:
                stats.errors.append(f"Could not read {card['url']}: {e}")
                continue
            job = {**card, **{k: v for k, v in detail.items() if v}}
            job["source"] = "indeed"
            job_id, is_new = db.upsert_job(job)
            if is_new:
                stats.new_jobs += 1
                evaluate_job(db, job_id, settings, profile, stats)
        if budget <= 0:
            stats.errors.append("Reached the page limit for this run (max_job_pages_per_run)")
            break


def discover_from_list(jobs: list[dict], db: DB, settings: dict, profile: dict, stats: RunStats,
                       source: str = "import") -> list[int]:
    ids = []
    for j in jobs:
        j = dict(j)
        j.setdefault("source", source)
        if not j.get("job_key"):
            from jobbot.indeed.search import job_key_from_url
            j["job_key"] = job_key_from_url(j.get("url") or f"{j.get('company')}|{j.get('title')}")
        stats.found += 1
        if db.find_duplicate(job_key=j["job_key"], url=j.get("url")):
            continue
        job_id, is_new = db.upsert_job(j)
        if is_new:
            stats.new_jobs += 1
            evaluate_job(db, job_id, settings, profile, stats)
            ids.append(job_id)
    return ids


# ---------------- applications ----------------
def apply_queue(db: DB, settings: dict, stats: RunStats) -> list[dict]:
    today = datetime.now(DUBAI).date().isoformat()
    limit = int(settings["daily_application_limit"])
    done_today = db.count_submitted_on(today) + len([
        j for j in db.list_jobs(status="ready_for_review", order="recent", limit=200)
        if (j.get("application_date") or "").startswith(today)])
    room = max(0, limit - done_today)
    approved = db.list_jobs(status="approved", order="score")
    cutoff = (datetime.now(DUBAI) - timedelta(days=14)).isoformat()
    fresh = [j for j in db.list_jobs(status=list(APPLY_QUEUE_STATUSES), min_score=settings["match_threshold"])
             if j["date_discovered"] >= cutoff]
    fresh.sort(key=lambda j: (j.get("category") != "medical_coding", -(j.get("score") or 0)))
    queue = approved + fresh
    return queue[:room] if room else []


def prepare_documents(db: DB, job: dict, profile: dict, stats: RunStats, use_ai: bool) -> dict:
    if job.get("cv_path") and Path(job["cv_path"]).exists():
        return job
    bd = job.get("score_breakdown") or {}
    matched = (bd.get("technical_skills") or {}).get("matched", [])
    docs = generate_application_documents(profile, job, matched, job.get("category") or "medical_coding", use_ai=use_ai)
    fields = dict(cv_version=docs["cv_version"], cv_path=docs["cv_pdf"], cover_letter_path=docs["cover_letter_pdf"])
    if job["status"] == "approved":
        db.update_job(job["id"], **fields)
        db.log_event(job["id"], "documents", docs["folder"], stats.run_id)
    else:
        db.set_status(job["id"], "prepared", docs["folder"], stats.run_id, **fields)
    stats.prepared += 1
    return db.get_job(job["id"])


def process_applications(session: BrowserSession | None, db: DB, settings: dict, profile: dict, stats: RunStats,
                         use_ai: bool = True) -> None:
    from jobbot.indeed.apply import run_apply
    allowed, why = auto_submit_allowed(settings)
    stats.auto_reason = why
    answerer = Answerer(profile)
    for job in apply_queue(db, settings, stats):
        try:
            job = prepare_documents(db, job, profile, stats, use_ai)
        except Exception as e:
            stats.errors.append(f"Documents for job #{job['id']} failed: {e}")
            log.exception("documents failed")
            continue
        stats.touched_job_ids.append(job["id"])
        if session is None:
            continue
        suspicious = any("automated tools" in f for f in (job.get("flags") or []))
        submit = (job["status"] == "approved" or allowed) and not suspicious
        try:
            res = run_apply(session, job, job["cv_path"], answerer, submit=submit)
        except PauseRequired:
            raise
        except Exception as e:
            stats.errors.append(f"Application for job #{job['id']} ({job.get('company')}) failed: {e}")
            log.exception("apply failed")
            db.set_status(job["id"], "needs_attention", f"error: {e}", stats.run_id)
            stats.needs_attention += 1
            continue
        extra = {"screenshot_path": res.screenshot or None,
                 "pending_questions": res.pending or None}
        if res.status == "submitted":
            extra.update(application_date=now_iso(), submission_confirmation=res.confirmation or res.detail)
            stats.submitted += 1
        elif res.status == "ready_for_review":
            extra.update(application_date=now_iso())
            stats.ready_for_review += 1
        elif res.status == "external_apply":
            stats.external += 1
        else:
            stats.needs_attention += 1
        db.set_status(job["id"], res.status, res.detail, stats.run_id, **extra)
        db.log_event(job["id"], "apply_answers", json.dumps(res.answered, ensure_ascii=False), stats.run_id)


# ---------------- run ----------------
def run(settings: dict, *, session_factory: Callable[[], BrowserSession] | None = None,
        jobs: list[dict] | None = None, use_ai: bool = True, scheduled: bool = False,
        notify_enabled: bool = True) -> RunStats:
    """jobs=None and session_factory set: search Indeed. jobs given: score/prepare those (no searching)."""
    p = paths()
    p.ensure()
    stats = RunStats(mode=settings["application_mode"])
    if scheduled and not is_scheduled_day(settings):
        log.info("Not a scheduled day in Asia/Dubai; nothing to do.")
        stats.errors.append("Skipped: not a scheduled day")
        return stats
    profile = load_profile()
    with RunLock(p.data / "run.lock"):
        db = DB()
        try:
            db.backup()
        except Exception as e:
            stats.errors.append(f"Backup failed: {e}")
        stats.run_id = db.start_run(stats.mode)
        try:
            from jobbot import telegram_bot
            telegram_bot.process_updates(db)  # pick up approvals sent since the last run
        except Exception as e:
            stats.errors.append(f"Telegram check failed: {e}")
        try:
            if jobs is not None:
                discover_from_list(jobs, db, settings, profile, stats)
                process_applications(None, db, settings, profile, stats, use_ai)
            elif session_factory is not None:
                with session_factory() as session:
                    try:
                        discover_with_browser(session, db, settings, profile, stats)
                        process_applications(session, db, settings, profile, stats, use_ai)
                    except PauseRequired as e:
                        stats.paused = f"{e.kind}: {e.detail}"
                        stats.errors.append(f"Paused for Anagha: {e.kind} ({e.detail}) at {e.url}")
                        session.screenshot("paused-" + e.kind)
            status = "paused" if stats.paused else "completed"
        except Exception as e:
            log.exception("run failed")
            stats.errors.append(f"Run failed: {e}")
            status = "failed"
        report_path = reports.write_daily(db, stats)
        if notify_enabled:
            try:
                from jobbot import telegram_bot
                telegram_bot.send_review_requests(db)
            except Exception as e:
                stats.errors.append(f"Telegram send failed: {e}")
        if datetime.now(DUBAI).strftime("%a") == "Sat" or not is_scheduled_day(settings, datetime.now(DUBAI) + timedelta(days=1)):
            try:
                reports.write_weekly(db)
            except Exception as e:
                stats.errors.append(f"Weekly report failed: {e}")
        db.finish_run(stats.run_id, status=status, found=stats.found, new_jobs=stats.new_jobs,
                      relevant=stats.relevant, prepared=stats.prepared, ready_for_review=stats.ready_for_review,
                      submitted=stats.submitted, errors=stats.errors, report_path=str(report_path))
        db.close()
    if notify_enabled:
        notify.after_run(stats, report_path)
    return stats
