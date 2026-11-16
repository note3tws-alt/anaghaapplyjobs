"""Command line: python -m jobbot <command>"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from jobbot import config
from jobbot.config import load_answers, load_profile, load_settings, paths, rules_fingerprint, save_settings

log = logging.getLogger("jobbot")


class RedactFilter(logging.Filter):
    PAT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d \-]{8,}\d")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        record.msg, record.args = self.PAT.sub("[redacted]", msg), None
        return True


def setup_logging(verbose: bool = False) -> None:
    p = paths()
    p.logs.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(p.logs / "jobbot.log", maxBytes=2_000_000, backupCount=10, encoding="utf-8")
    sh = logging.StreamHandler()
    for h in (fh, sh):
        h.setFormatter(fmt)
        h.addFilter(RedactFilter())
        root.addHandler(h)


def session_factory(settings: dict, headless: bool | None = None):
    from jobbot.indeed.browser import BrowserSession
    return lambda: BrowserSession(settings, headless=headless)


# ---------------- commands ----------------
def cmd_init(a) -> int:
    created = config.init_files()
    from jobbot.db import DB
    DB().close()
    for c in created:
        print("created", c)
    if a.cv:
        dst = paths().cv_dir / "Anagha_P_CV.pdf"
        shutil.copy(a.cv, dst)
        print("copied CV to", dst)
        return cmd_check_cv(argparse.Namespace(cv=str(dst), write_private=True))
    print("Next: fill config/candidate_private.yaml (or run: python -m jobbot init --cv path\\to\\Anagha_P_CV.pdf)")
    return 0


def cmd_check_cv(a) -> int:
    """Compare the CV PDF with config/candidate_profile.yaml and report anything that differs."""
    import pdfplumber
    with pdfplumber.open(a.cv) as pdf:
        text = "\n".join(pg.extract_text() or "" for pg in pdf.pages)
    profile = load_profile()
    low = re.sub(r"\s+", " ", text.lower())
    checks = {
        "Name": profile["name"],
        "CPC certification": "Certified Professional Coder (CPC)",
        "CPC date": profile["certifications"][0]["date"],
        "Exam score": "90%",
        "Employer": profile["experience"][0]["employer"],
        "Job title": "Insurance Coordinator Trainee",
        "Employment start": profile["experience"][0]["start"],
        "Internship hours": "270",
        "Internship grade": "A+",
        "eClaimLink": "eClaimLink",
        "Mediware": "Mediware",
        "MSc": "MSc Zoology",
        "BSc": "BSc Zoology",
        "Visa status": profile["visa_status_on_cv"],
    }
    bad = 0
    for label, needle in checks.items():
        ok = needle.lower() in low
        bad += not ok
        print(f"  [{'ok' if ok else 'MISSING'}] {label}: {needle}")
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    phone = re.search(r"\+971[\d ]{8,13}", text)
    linkedin = re.search(r"linkedin\.com/in/[\w-]+", text)
    aapc = re.search(r"AAPC ID:\s*(\d+)", text)
    found = {"email": email.group(0) if email else "", "phone": phone.group(0).strip() if phone else "",
             "linkedin": linkedin.group(0) if linkedin else "", "aapc_id": aapc.group(1) if aapc else ""}
    print("  contact details found:", ", ".join(k for k, v in found.items() if v) or "none")
    if getattr(a, "write_private", False):
        import yaml
        f = paths().config / "candidate_private.yaml"
        cur = yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else {}
        cur = cur or {}
        for k, v in found.items():
            if v and not cur.get(k):
                cur[k] = v
        f.write_text(yaml.safe_dump(cur, sort_keys=False), encoding="utf-8")
        print("  saved contact details to", f, "(gitignored)")
    print("CV check:", "all key facts match" if not bad else f"{bad} fact(s) differ: update config/candidate_profile.yaml")
    return 0 if not bad else 1


def cmd_login(a) -> int:
    from jobbot.indeed.browser import BrowserSession, detect_blocker, is_signed_in
    s = load_settings()
    print("A browser window will open on Indeed UAE using the job bot's own profile.")
    print("Sign in to Anagha's Indeed account yourself (and complete any verification).")
    print("This window closes by itself once you are signed in, or after 10 minutes.")
    with BrowserSession(s, headless=False, pace_seconds=0) as b:
        b.page.goto(b.base_url + "/account/login", wait_until="domcontentloaded")
        deadline = time.time() + 600
        while time.time() < deadline:
            time.sleep(3)
            try:
                if "indeed.com" in b.page.url and "secure.indeed.com" not in b.page.url and not detect_blocker(b.page) \
                        and is_signed_in(b.page):
                    print("Signed in. The session is saved in", b.profile_dir)
                    time.sleep(2)
                    return 0
            except Exception:
                continue
    print("Not signed in yet. Run this command again when ready.")
    return 1


def cmd_run(a) -> int:
    from jobbot.pipeline import run
    s = load_settings()
    stats = run(s, session_factory=session_factory(s, headless=True if a.headless else None),
                use_ai=not a.no_ai, scheduled=a.scheduled)
    print(json.dumps({k: v for k, v in stats.__dict__.items() if k not in ("rejected", "touched_job_ids")}, indent=1))
    return 0 if not stats.paused else 2


def cmd_demo(a) -> int:
    """Full review-mode run against the offline mock site, in a throwaway data folder."""
    from jobbot.indeed.browser import BrowserSession
    from jobbot.mock_indeed import MockIndeed
    from jobbot.pipeline import run
    tmp = Path(tempfile.mkdtemp(prefix="jobbot-demo-"))
    # Copy config so the demo never touches real settings; use placeholder contact details if none exist.
    shutil.copytree(paths().config, tmp / "config")
    priv = tmp / "config" / "candidate_private.yaml"
    if not priv.exists() or "@" not in priv.read_text(encoding="utf-8"):
        priv.write_text("email: demo@example.invalid\nphone: '+971 00 000 0000'\n", encoding="utf-8")
    os.environ["JOBBOT_CONFIG"] = str(tmp / "config")
    os.environ["JOBBOT_DATA"] = str(tmp / "data")
    os.environ["JOBBOT_REPORTS"] = str(tmp / "reports")
    s = load_settings()
    s["application_mode"] = "review"
    s["seconds_between_page_loads"] = 2
    s["max_searches_per_run"] = 6
    with MockIndeed() as m:
        s["browser"]["base_url"] = m.base_url
        stats = run(s, session_factory=lambda: BrowserSession(s, headless=a.headless, pace_seconds=0.5,
                                                              profile_dir=tmp / "profile"),
                    use_ai=False, notify_enabled=False)
        print(f"\nDemo finished. Submissions made to the mock site: {len(m.submissions)} (review mode must be 0)")
    print(f"Found {stats.found}, relevant {stats.relevant}, prepared {stats.prepared}, "
          f"ready for review {stats.ready_for_review}, needs attention {stats.needs_attention}")
    print("Demo files:", tmp)
    return 0


def cmd_import(a) -> int:
    from jobbot.pipeline import run
    data = json.loads(Path(a.file).read_text(encoding="utf-8"))
    s = load_settings()
    stats = run(s, jobs=data if isinstance(data, list) else data.get("jobs", []), use_ai=not a.no_ai,
                notify_enabled=False)
    print(f"Imported {stats.new_jobs} new vacancies; {stats.relevant} relevant; {stats.prepared} prepared.")
    return 0


def cmd_apply(a) -> int:
    from jobbot.db import DB
    from jobbot.indeed.browser import BrowserSession, PauseRequired
    from jobbot.indeed.apply import run_apply
    from jobbot.pipeline import RunStats, prepare_documents
    from jobbot.screening import Answerer
    s = load_settings()
    db = DB()
    job = db.get_job(a.job)
    if not job:
        print("No such job"); return 1
    if a.submit and job["status"] != "approved":
        print("Only jobs Anagha approved (status 'approved') can be submitted from here."); return 1
    prof = load_profile()
    job = prepare_documents(db, job, prof, RunStats(), use_ai=not a.no_ai)
    with BrowserSession(s, headless=False) as b:
        try:
            res = run_apply(b, job, job["cv_path"], Answerer(prof), submit=a.submit)
        except PauseRequired as e:
            print("Paused:", e); return 2
        print(json.dumps(res.to_dict(), indent=1, ensure_ascii=False))
        extra = {"screenshot_path": res.screenshot or None, "pending_questions": res.pending or None}
        if res.status == "submitted":
            from jobbot.db import now_iso
            extra.update(application_date=now_iso(), submission_confirmation=res.confirmation)
        db.set_status(job["id"], res.status, res.detail, **extra)
        if not a.submit and res.status == "ready_for_review":
            input("The form is filled. Check it in the window; press Enter here to close (nothing is submitted)...")
    return 0


def cmd_authorise(a) -> int:
    s = load_settings()
    answers = load_answers()
    verified = [r for r in answers.get("answers", []) if r.get("verified")]
    print("AUTO-APPLY RULES TO AUTHORISE\n")
    print(f"  Locations: {', '.join(s['locations'])} (strict: {s.get('only_apply_in_search_locations', True)})")
    print(f"  Minimum score: {s['match_threshold']}   Daily limit: {s['daily_application_limit']}"
          f"   Minimum salary: AED {s['minimum_salary_aed']}")
    print("  Verified screening answers the bot may give:")
    for r in verified:
        print(f"    - {r['id']}: {r.get('answer')}  (source: {r.get('source', '')})")
    print("  The bot will ALWAYS stop for: unknown questions, legal declarations, terms/consent, salary,")
    print("  sensitive personal data, unverified work authorisation, CAPTCHA and sign-in.\n")
    typed = input("Anagha, type I AUTHORISE to allow submissions under these rules: ").strip()
    if typed != "I AUTHORISE":
        print("Not authorised. Nothing changed."); return 1
    from jobbot.db import now_iso
    s["application_mode"] = "auto"
    s["authorisation"] = {"authorised": True, "authorised_by": a.name or "Anagha P", "authorised_at": now_iso(),
                          "rules_fingerprint": rules_fingerprint(s, answers)}
    save_settings(s)
    print("Authorised. Mode is now auto. Changing rules or answers later switches submission off until you authorise again.")
    return 0


def cmd_revoke(a) -> int:
    s = load_settings()
    s["application_mode"] = "review"
    s["authorisation"] = {"authorised": False, "authorised_by": None, "authorised_at": None, "rules_fingerprint": None}
    save_settings(s)
    print("Auto-apply switched off. Mode is review.")
    return 0


def cmd_dashboard(a) -> int:
    import uvicorn
    from jobbot.dashboard.app import create_app
    url = f"http://127.0.0.1:{a.port}"
    if a.open:
        webbrowser.open(url)
    print("Dashboard on", url, "(only reachable from this computer)")
    uvicorn.run(create_app(), host="127.0.0.1", port=a.port, log_level="warning")
    return 0


def cmd_report(a) -> int:
    from jobbot import reports
    from jobbot.db import DB
    db = DB()
    if a.weekly:
        print(reports.write_weekly(db))
    else:
        from jobbot.pipeline import RunStats
        print(reports.write_daily(db, RunStats(mode=load_settings()["application_mode"])))
    return 0


def cmd_backup(a) -> int:
    from jobbot.db import DB
    print(DB().backup())
    return 0


def cmd_status(a) -> int:
    from jobbot.db import DB
    from jobbot.notify import email_status
    s = load_settings()
    db = DB()
    print(json.dumps(db.overview(), indent=1))
    print("mode:", s["application_mode"], "| auto-submit:", config.auto_submit_allowed(s)[1])
    print("email:", email_status()[1])
    return 0


def cmd_doctor(a) -> int:
    ok = True
    print("Python", sys.version.split()[0], "(needs 3.10+)")
    ok &= sys.version_info >= (3, 10)
    for mod in ("fastapi", "uvicorn", "playwright", "yaml", "docx", "reportlab", "pdfplumber", "anthropic"):
        try:
            __import__(mod)
            print("  ok", mod)
        except ImportError:
            print("  MISSING", mod); ok = False
    try:
        s = load_settings()
        print("  settings ok: mode", s["application_mode"], "| locations", s["locations"])
    except Exception as e:
        print("  settings problem:", e); ok = False
    prof = load_profile()
    if not prof["contact"].get("email"):
        print("  WARNING: no email in config/candidate_private.yaml (run: python -m jobbot init --cv <pdf>)")
    from jobbot.ai import ai_available
    from jobbot.notify import email_status
    print("  AI writing:", "Claude API key set" if ai_available() else "off (templates)")
    print("  email:", email_status()[1])
    from jobbot import telegram_bot
    print("  telegram approvals:", "configured" if telegram_bot.configured() else "off (python -m jobbot telegram-setup)")
    if a.live:
        from jobbot.indeed import selectors as S
        from jobbot.indeed.browser import BrowserSession, PauseRequired, first, is_signed_in
        from jobbot.indeed.search import parse_results, search_url
        with BrowserSession(load_settings(), headless=False) as b:
            try:
                b.goto(b.base_url + "/")
                print("  signed in:", is_signed_in(b.page))
                b.goto(search_url(b.base_url, "Medical Coder", "Dubai"))
                cards = parse_results(b.page, b.base_url)
                print(f"  search page: {len(cards)} cards parsed;", "first:", cards[0] if cards else None)
                if cards:
                    b.goto(cards[0]["url"])
                    print("  description found:", first(b.page, S.JOB_DESCRIPTION) is not None)
            except PauseRequired as e:
                print("  paused:", e); ok = False
    print("doctor:", "all good" if ok else "problems found")
    return 0 if ok else 1


def cmd_telegram(a) -> int:
    from jobbot import telegram_bot
    if not telegram_bot.configured():
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env first (see python -m jobbot telegram-setup)."); return 1
    from jobbot.db import DB
    db = DB()
    print("Sent", telegram_bot.send_review_requests(db), "waiting application(s) to Telegram.")
    db.close()
    if a.once:
        return 0
    telegram_bot.listen_forever()
    return 0


def cmd_telegram_setup(a) -> int:
    from jobbot import telegram_bot
    from jobbot.config import env
    if not env("TELEGRAM_BOT_TOKEN"):
        print("1. In Telegram, open @BotFather, send /newbot and follow the steps.")
        print("2. Put the token it gives you in .env as TELEGRAM_BOT_TOKEN=...  (never share it)")
        print("3. Open your new bot in Telegram and send /start, then run this command again."); return 1
    chat = telegram_bot.find_chat_id()
    if not chat:
        print("No message found. Send /start to your bot in Telegram, then run this again."); return 1
    envf = paths().root / ".env"
    lines = envf.read_text(encoding="utf-8").splitlines() if envf.exists() else []
    lines = [l for l in lines if not l.startswith("TELEGRAM_CHAT_ID=")] + [f"TELEGRAM_CHAT_ID={chat}"]
    envf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["TELEGRAM_CHAT_ID"] = chat
    telegram_bot.send_text("Job bot connected. Applications waiting for review will arrive here with Approve / Skip buttons.")
    print("Saved TELEGRAM_CHAT_ID to .env and sent a test message.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jobbot", description="Anagha's Indeed UAE job application assistant")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="create local config, folders and database"); p.add_argument("--cv")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("check-cv", help="compare the CV PDF with the profile"); p.add_argument("cv")
    p.add_argument("--write-private", action="store_true"); p.set_defaults(fn=cmd_check_cv)
    sub.add_parser("login", help="sign in to Indeed once in the bot's own browser").set_defaults(fn=cmd_login)
    p = sub.add_parser("run", help="search, score, prepare and apply (per mode)")
    p.add_argument("--scheduled", action="store_true", help="exit on non-scheduled days (used by Task Scheduler)")
    p.add_argument("--no-ai", action="store_true"); p.add_argument("--headless", action="store_true")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("demo", help="safe rehearsal against an offline mock site"); p.add_argument("--headless", action="store_true")
    p.set_defaults(fn=cmd_demo)
    p = sub.add_parser("import-jobs", help="score and prepare vacancies from a JSON file"); p.add_argument("file")
    p.add_argument("--no-ai", action="store_true"); p.set_defaults(fn=cmd_import)
    p = sub.add_parser("apply", help="fill one job now in a visible browser"); p.add_argument("--job", type=int, required=True)
    p.add_argument("--submit", action="store_true", help="submit (approved jobs only)"); p.add_argument("--no-ai", action="store_true")
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("authorise", help="Anagha authorises auto-apply rules"); p.add_argument("--name")
    p.set_defaults(fn=cmd_authorise)
    sub.add_parser("revoke", help="switch auto-apply off").set_defaults(fn=cmd_revoke)
    p = sub.add_parser("dashboard", help="start the web dashboard"); p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true"); p.set_defaults(fn=cmd_dashboard)
    p = sub.add_parser("report", help="write a report now"); p.add_argument("--weekly", action="store_true")
    p.set_defaults(fn=cmd_report)
    sub.add_parser("backup", help="back up the database").set_defaults(fn=cmd_backup)
    sub.add_parser("status", help="show counts and settings").set_defaults(fn=cmd_status)
    p = sub.add_parser("telegram", help="send waiting applications to Telegram and listen for Approve/Skip")
    p.add_argument("--once", action="store_true", help="send and exit instead of listening"); p.set_defaults(fn=cmd_telegram)
    sub.add_parser("telegram-setup", help="connect the Telegram bot to Anagha's chat").set_defaults(fn=cmd_telegram_setup)
    p = sub.add_parser("doctor", help="check the installation"); p.add_argument("--live", action="store_true")
    p.set_defaults(fn=cmd_doctor)
    a = ap.parse_args(argv)
    setup_logging(a.verbose)
    return a.fn(a)
