"""SQLite storage: vacancies, application history, runs, backups."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from jobbot.config import paths

DUBAI = ZoneInfo("Asia/Dubai")

# Application statuses, in rough lifecycle order.
STATUSES = (
    "discovered",        # found, not yet scored
    "rejected",          # below review threshold or filtered (reason in reject_reason)
    "possible",          # 50-64: shown for review, never auto-applied
    "shortlisted",       # at or above match threshold
    "prepared",          # tailored CV / cover letter generated
    "ready_for_review",  # form filled up to the final submit page, waiting for Anagha
    "approved",          # Anagha approved it in the dashboard; next run may submit
    "needs_attention",   # stopped: unknown question, login, CAPTCHA, external site...
    "external_apply",    # employer site, not Indeed Apply: she applies by hand
    "submitted",         # submission confirmed
    "interview",
    "offer",
    "rejected_by_employer",
    "withdrawn",
    "skipped",           # she chose to skip
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'indeed',
    company TEXT,
    title TEXT,
    location TEXT,
    salary TEXT,
    salary_min_aed INTEGER,
    url TEXT,
    apply_url TEXT,
    apply_type TEXT,
    description TEXT,
    posted TEXT,
    date_discovered TEXT NOT NULL,
    search_term TEXT,
    category TEXT,
    score INTEGER,
    classification TEXT,
    score_breakdown TEXT,
    extracted TEXT,
    flags TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    reject_reason TEXT,
    cv_version TEXT,
    cv_path TEXT,
    cover_letter_path TEXT,
    application_date TEXT,
    submission_confirmation TEXT,
    pending_questions TEXT,
    screenshot_path TEXT,
    notes TEXT,
    company_norm_title TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_ct ON jobs(company_norm_title);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    run_id INTEGER,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    mode TEXT,
    status TEXT,
    found INTEGER DEFAULT 0,
    new_jobs INTEGER DEFAULT 0,
    relevant INTEGER DEFAULT 0,
    prepared INTEGER DEFAULT 0,
    ready_for_review INTEGER DEFAULT 0,
    submitted INTEGER DEFAULT 0,
    errors TEXT,
    report_path TEXT
);
"""


def now_iso() -> str:
    return datetime.now(DUBAI).isoformat(timespec="seconds")


def norm(s: str | None) -> str:
    s = (s or "").lower()
    s = re.sub(r"\b(llc|l\.l\.c|fze|fzco|fz-llc|plc|ltd|limited|co|company|group|the)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def norm_title(s: str | None) -> str:
    s = norm(s)
    s = re.sub(r"\b(urgent|hiring|immediate|joiner|joining|dubai|sharjah|ajman|abu dhabi|uae|onsite|on site|remote)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def company_title_key(company: str | None, title: str | None) -> str:
    return f"{norm(company)}|{norm_title(title)}"


class DB:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or paths().db)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---------- jobs ----------
    def get_job(self, job_id: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _row(r)

    def get_job_by_key(self, key: str) -> dict | None:
        return _row(self.conn.execute("SELECT * FROM jobs WHERE job_key=?", (key,)).fetchone())

    def find_duplicate(self, *, job_key: str | None = None, url: str | None = None,
                       company: str | None = None, title: str | None = None,
                       exclude_id: int | None = None) -> dict | None:
        """Duplicate check by job ID, URL, then company + job title."""
        q, args = [], []
        if job_key:
            q.append("job_key=?"); args.append(job_key)
        if url:
            q.append("url=?"); args.append(url)
        if company and title:
            q.append("company_norm_title=?"); args.append(company_title_key(company, title))
        if not q:
            return None
        sql = f"SELECT * FROM jobs WHERE ({' OR '.join(q)})"
        if exclude_id:
            sql += " AND id<>?"; args.append(exclude_id)
        sql += " ORDER BY id LIMIT 1"
        return _row(self.conn.execute(sql, args).fetchone())

    def already_applied(self, company: str | None, title: str | None, exclude_id: int | None = None) -> dict | None:
        """Was this company + title already applied to, or is it on the way?"""
        sql = ("SELECT * FROM jobs WHERE company_norm_title=? AND status IN "
               "('submitted','interview','offer','rejected_by_employer','ready_for_review','approved')")
        args: list[Any] = [company_title_key(company, title)]
        if exclude_id:
            sql += " AND id<>?"; args.append(exclude_id)
        return _row(self.conn.execute(sql, args).fetchone())

    def upsert_job(self, job: dict) -> tuple[int, bool]:
        """Insert a new vacancy. Returns (id, is_new). Existing rows keep their status and history."""
        existing = self.get_job_by_key(job["job_key"])
        if existing:
            return existing["id"], False
        now = now_iso()
        fields = {
            "job_key": job["job_key"], "source": job.get("source", "indeed"),
            "company": job.get("company"), "title": job.get("title"), "location": job.get("location"),
            "salary": job.get("salary"), "url": job.get("url"), "apply_url": job.get("apply_url"),
            "apply_type": job.get("apply_type"), "description": job.get("description"),
            "posted": job.get("posted"), "search_term": job.get("search_term"),
            "date_discovered": now, "updated_at": now, "status": "discovered",
            "company_norm_title": company_title_key(job.get("company"), job.get("title")),
        }
        with self.tx() as c:
            cur = c.execute(f"INSERT INTO jobs ({','.join(fields)}) VALUES ({','.join('?' * len(fields))})",
                            list(fields.values()))
            job_id = cur.lastrowid
        self.log_event(job_id, "discovered", job.get("search_term"))
        return job_id, True

    def update_job(self, job_id: int, **fields: Any) -> None:
        if not fields:
            return
        for k in ("score_breakdown", "extracted", "flags", "pending_questions"):
            if k in fields and not isinstance(fields[k], (str, type(None))):
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        if "status" in fields and fields["status"] not in STATUSES:
            raise ValueError(f"unknown status {fields['status']}")
        if "company" in fields or "title" in fields:
            cur = self.get_job(job_id) or {}
            fields["company_norm_title"] = company_title_key(fields.get("company", cur.get("company")),
                                                             fields.get("title", cur.get("title")))
        fields["updated_at"] = now_iso()
        sets = ",".join(f"{k}=?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE jobs SET {sets} WHERE id=?", [*fields.values(), job_id])

    def set_status(self, job_id: int, status: str, detail: str | None = None, run_id: int | None = None,
                   **extra: Any) -> None:
        self.update_job(job_id, status=status, **extra)
        self.log_event(job_id, f"status:{status}", detail, run_id)

    def list_jobs(self, status: str | list[str] | None = None, min_score: int | None = None,
                  search: str | None = None, limit: int = 500, order: str = "score") -> list[dict]:
        sql, args = "SELECT * FROM jobs WHERE 1=1", []
        if status:
            st = [status] if isinstance(status, str) else list(status)
            sql += f" AND status IN ({','.join('?' * len(st))})"; args += st
        if min_score is not None:
            sql += " AND score>=?"; args.append(min_score)
        if search:
            sql += " AND (company LIKE ? OR title LIKE ? OR location LIKE ?)"
            args += [f"%{search}%"] * 3
        sql += {"score": " ORDER BY score DESC, id DESC", "recent": " ORDER BY id DESC",
                "applied": " ORDER BY application_date DESC, id DESC"}.get(order, " ORDER BY id DESC")
        sql += " LIMIT ?"; args.append(limit)
        return [_row(r) for r in self.conn.execute(sql, args)]

    def count_submitted_on(self, day: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('submitted','interview','offer','rejected_by_employer') "
            "AND substr(application_date,1,10)=?", (day,)).fetchone()[0]

    # ---------- events ----------
    def log_event(self, job_id: int | None, event: str, detail: str | None = None, run_id: int | None = None) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO events (job_id, run_id, ts, event, detail) VALUES (?,?,?,?,?)",
                      (job_id, run_id, now_iso(), event, detail))

    def events_for(self, job_id: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM events WHERE job_id=? ORDER BY id", (job_id,))]

    # ---------- runs ----------
    def start_run(self, mode: str) -> int:
        with self.tx() as c:
            return c.execute("INSERT INTO runs (started_at, mode, status) VALUES (?,?,?)",
                             (now_iso(), mode, "running")).lastrowid

    def finish_run(self, run_id: int, **fields: Any) -> None:
        if "errors" in fields and not isinstance(fields["errors"], str):
            fields["errors"] = json.dumps(fields["errors"], ensure_ascii=False)
        fields["finished_at"] = now_iso()
        sets = ",".join(f"{k}=?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE runs SET {sets} WHERE id=?", [*fields.values(), run_id])

    def list_runs(self, limit: int = 30) -> list[dict]:
        out = []
        for r in self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)):
            d = dict(r)
            d["errors"] = json.loads(d["errors"]) if d.get("errors") else []
            out.append(d)
        return out

    # ---------- stats ----------
    def overview(self) -> dict:
        def c(sql: str, *a: Any) -> int:
            return self.conn.execute(sql, a).fetchone()[0]
        return {
            "jobs_discovered": c("SELECT COUNT(*) FROM jobs"),
            "jobs_shortlisted": c("SELECT COUNT(*) FROM jobs WHERE status NOT IN ('discovered','rejected','possible')"),
            "possible_matches": c("SELECT COUNT(*) FROM jobs WHERE status='possible'"),
            "applications_submitted": c("SELECT COUNT(*) FROM jobs WHERE status IN ('submitted','interview','offer','rejected_by_employer')"),
            "interviews": c("SELECT COUNT(*) FROM jobs WHERE status IN ('interview','offer')"),
            "pending_applications": c("SELECT COUNT(*) FROM jobs WHERE status IN ('shortlisted','prepared','ready_for_review','approved','needs_attention','external_apply')"),
            "needs_attention": c("SELECT COUNT(*) FROM jobs WHERE status='needs_attention'"),
            "ready_for_review": c("SELECT COUNT(*) FROM jobs WHERE status='ready_for_review'"),
            "rejections": c("SELECT COUNT(*) FROM jobs WHERE status='rejected_by_employer'"),
            "filtered_out": c("SELECT COUNT(*) FROM jobs WHERE status='rejected'"),
        }

    def daily_stats(self, days: int = 14) -> list[dict]:
        start = (datetime.now(DUBAI) - timedelta(days=days - 1)).date()
        out = []
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            row = self.conn.execute(
                """SELECT
                    SUM(CASE WHEN substr(date_discovered,1,10)=? THEN 1 ELSE 0 END),
                    SUM(CASE WHEN substr(date_discovered,1,10)=? AND score>=50 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN substr(application_date,1,10)=? AND status IN ('submitted','interview','offer','rejected_by_employer') THEN 1 ELSE 0 END)
                   FROM jobs""", (d, d, d)).fetchone()
            out.append({"date": d, "discovered": row[0] or 0, "relevant": row[1] or 0, "submitted": row[2] or 0})
        return out

    # ---------- backup ----------
    def backup(self, keep: int = 21) -> Path:
        p = paths()
        p.backups.mkdir(parents=True, exist_ok=True)
        dst = p.backups / f"jobbot-{datetime.now(DUBAI):%Y%m%d-%H%M%S}.sqlite3"
        bconn = sqlite3.connect(dst)
        with bconn:
            self.conn.backup(bconn)
        bconn.close()
        olds = sorted(p.backups.glob("jobbot-*.sqlite3"))
        for old in olds[:-keep]:
            old.unlink(missing_ok=True)
        return dst


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("score_breakdown", "extracted", "flags", "pending_questions"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (TypeError, ValueError):
                pass
    return d
