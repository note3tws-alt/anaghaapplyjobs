"""FastAPI backend for the dashboard. Binds to 127.0.0.1 only (see cli.cmd_dashboard)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from jobbot import config
from jobbot.config import auto_submit_allowed, load_settings, paths, save_settings
from jobbot.db import DB, STATUSES

STATIC = Path(__file__).resolve().parent / "static"

# Statuses Anagha can set by hand from the tracker.
MANUAL_STATUSES = {"approved", "skipped", "submitted", "interview", "offer", "rejected_by_employer",
                   "withdrawn", "shortlisted", "needs_attention", "external_apply"}

JOB_LIST_FIELDS = ("id", "company", "title", "location", "salary", "url", "apply_url", "apply_type", "score",
                   "classification", "status", "reject_reason", "category", "date_discovered", "application_date",
                   "cv_version", "submission_confirmation", "notes", "flags", "pending_questions")


class StatusUpdate(BaseModel):
    status: str
    note: str | None = None


class NoteUpdate(BaseModel):
    notes: str


def _slim(j: dict) -> dict:
    return {k: j.get(k) for k in JOB_LIST_FIELDS}


def create_app() -> FastAPI:
    app = FastAPI(title="Anagha's Job Assistant", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = (request.client.host if request.client else "") or ""
        if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
            return JSONResponse({"detail": "local access only"}, status_code=403)
        return await call_next(request)

    def db() -> DB:
        return DB()

    @app.get("/api/overview")
    def overview():
        d = db()
        try:
            s = load_settings()
            allowed, why = auto_submit_allowed(s)
            runs = d.list_runs(5)
            return {"counts": d.overview(), "daily": d.daily_stats(14), "mode": s["application_mode"],
                    "auto_submit": allowed, "auto_reason": why, "last_runs": runs}
        finally:
            d.close()

    @app.get("/api/jobs")
    def jobs(status: str | None = None, min_score: int | None = None, q: str | None = None,
             view: str = Query("opportunities")):
        d = db()
        try:
            if view == "tracker":
                st = ["ready_for_review", "approved", "needs_attention", "external_apply", "submitted", "interview",
                      "offer", "rejected_by_employer", "withdrawn", "prepared"]
                rows = d.list_jobs(status=status or st, search=q, order="applied")
            else:
                rows = d.list_jobs(status=status, min_score=min_score, search=q, order="score")
            return [_slim(r) for r in rows]
        finally:
            d.close()

    @app.get("/api/jobs/{job_id}")
    def job(job_id: int):
        d = db()
        try:
            j = d.get_job(job_id)
            if not j:
                raise HTTPException(404)
            j["events"] = d.events_for(job_id)
            j["has_cv"] = bool(j.get("cv_path") and Path(j["cv_path"]).exists())
            j["has_letter"] = bool(j.get("cover_letter_path") and Path(j["cover_letter_path"]).exists())
            j["has_screenshot"] = bool(j.get("screenshot_path") and Path(j["screenshot_path"]).exists())
            return j
        finally:
            d.close()

    @app.post("/api/jobs/{job_id}/status")
    def set_status(job_id: int, body: StatusUpdate):
        if body.status not in MANUAL_STATUSES:
            raise HTTPException(400, f"status must be one of {sorted(MANUAL_STATUSES)}")
        d = db()
        try:
            j = d.get_job(job_id)
            if not j:
                raise HTTPException(404)
            extra: dict[str, Any] = {}
            if body.status == "submitted" and not j.get("application_date"):
                from jobbot.db import now_iso
                extra["application_date"] = now_iso()
                extra["submission_confirmation"] = "Marked submitted by Anagha"
            d.set_status(job_id, body.status, body.note or "set in dashboard", **extra)
            return _slim(d.get_job(job_id))
        finally:
            d.close()

    @app.post("/api/jobs/{job_id}/notes")
    def set_notes(job_id: int, body: NoteUpdate):
        d = db()
        try:
            d.update_job(job_id, notes=body.notes[:4000])
            d.log_event(job_id, "note", body.notes[:200])
            return {"ok": True}
        finally:
            d.close()

    @app.get("/api/jobs/{job_id}/file/{kind}")
    def job_file(job_id: int, kind: str):
        d = db()
        try:
            j = d.get_job(job_id) or {}
        finally:
            d.close()
        col = {"cv": "cv_path", "letter": "cover_letter_path", "screenshot": "screenshot_path"}.get(kind)
        if not col or not j.get(col):
            raise HTTPException(404)
        f = Path(j[col]).resolve()
        if not f.exists() or paths().data.resolve() not in f.parents:
            raise HTTPException(404)
        return FileResponse(f)

    @app.get("/api/reports")
    def report_list():
        out = {}
        for kind in ("daily", "weekly"):
            folder = paths().reports / kind
            out[kind] = sorted((p.stem for p in folder.glob("*.md")), reverse=True) if folder.exists() else []
        d = db()
        try:
            out["daily_stats"] = d.daily_stats(28)
            out["runs"] = d.list_runs(30)
        finally:
            d.close()
        return out

    @app.get("/api/reports/{kind}/{name}", response_class=HTMLResponse)
    def report(kind: str, name: str):
        if kind not in ("daily", "weekly") or "/" in name or "\\" in name or ".." in name:
            raise HTTPException(400)
        f = paths().reports / kind / f"{name}.html"
        if not f.exists():
            raise HTTPException(404)
        return HTMLResponse(f.read_text(encoding="utf-8"))

    @app.get("/api/settings")
    def get_settings():
        s = load_settings()
        allowed, why = auto_submit_allowed(s)
        return {"settings": s, "auto_submit": allowed, "auto_reason": why}

    @app.put("/api/settings")
    def put_settings(body: dict):
        cur = load_settings()
        new = dict(cur)
        editable = ("match_threshold", "review_threshold", "daily_application_limit", "minimum_salary_aed",
                    "locations", "job_titles", "schedule", "application_mode", "posted_within_days",
                    "max_searches_per_run", "only_apply_in_search_locations")
        for k in editable:
            if k in body:
                new[k] = body[k]
        if new.get("application_mode") == "auto" and not (cur.get("authorisation") or {}).get("authorised"):
            raise HTTPException(400, "Auto mode needs Anagha's authorisation first: run 'python -m jobbot authorise'")
        try:
            save_settings(new)
        except ValueError as e:
            raise HTTPException(400, str(e))
        allowed, why = auto_submit_allowed(new)
        sched_changed = new.get("schedule") != cur.get("schedule")
        return {"settings": new, "auto_submit": allowed, "auto_reason": why,
                "note": ("Schedule saved. Run scripts\\windows\\register_task.ps1 again to apply it to Task Scheduler."
                         if sched_changed else None)}

    @app.get("/api/meta")
    def meta():
        return {"statuses": STATUSES, "manual_statuses": sorted(MANUAL_STATUSES)}

    if (STATIC / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

        @app.get("/{path:path}", response_class=HTMLResponse)
        def spa(path: str):
            if path.startswith("api"):
                raise HTTPException(404)
            return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))
    return app
