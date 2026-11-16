"""Telegram approvals: the bot sends each filled application with Approve / Skip buttons.

Only the chat in TELEGRAM_CHAT_ID is obeyed; messages from anyone else are ignored. Approving a job
sets it to 'approved', and the next run submits it (if every answer on the form is verified).
Setup: create a bot with @BotFather, put TELEGRAM_BOT_TOKEN in .env, send /start to the bot, then run
`python -m jobbot telegram-setup` to find and save the chat ID.
"""
from __future__ import annotations

import html
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from jobbot.config import env, paths
from jobbot.db import DB

log = logging.getLogger("jobbot.telegram")

APPROVABLE = ("ready_for_review", "prepared", "shortlisted", "possible")
SKIPPABLE = APPROVABLE + ("needs_attention", "approved", "external_apply")


def configured() -> bool:
    return bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID"))


def call(method: str, **params) -> dict:
    base = env("TELEGRAM_API_BASE", "https://api.telegram.org")
    url = f"{base}/bot{env('TELEGRAM_BOT_TOKEN')}/{method}"
    data = json.dumps(params).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    timeout = int(params.get("timeout", 0)) + 15
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram {method} failed: HTTP {e.code}") from None
    if not out.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {out.get('description')}")
    return out.get("result")


def _job_text(j: dict) -> str:
    lines = [f"<b>{html.escape(j.get('title') or '')}</b>",
             f"{html.escape(j.get('company') or '')} · {html.escape(j.get('location') or '')}",
             f"Score {j.get('score')} ({html.escape(j.get('classification') or '')})"]
    if j.get("salary"):
        lines.append(f"Salary: {html.escape(j['salary'])}")
    if j["status"] == "ready_for_review":
        lines.append("Form filled with verified answers. Approve to submit on the next run.")
    elif j["status"] == "needs_attention":
        qs = j.get("pending_questions") or []
        lines.append("Stopped on: " + "; ".join(html.escape(q.get("question", "")) for q in qs)[:600])
        lines.append("Answer these on Indeed yourself, or add a verified answer, then approve.")
    for f in (j.get("flags") or [])[:3]:
        lines.append(f"⚠ {html.escape(f)}")
    if j.get("url"):
        lines.append(f"<a href=\"{html.escape(j['url'])}\">Open on Indeed</a>")
    return "\n".join(lines)


def _buttons(j: dict) -> dict:
    row = []
    if j["status"] in APPROVABLE:
        row.append({"text": "✅ Approve", "callback_data": f"approve:{j['id']}"})
    row.append({"text": "⏭ Skip", "callback_data": f"skip:{j['id']}"})
    return {"inline_keyboard": [row]}


def send_review_requests(db: DB) -> int:
    """Send every job waiting for Anagha that has not been sent yet. Returns how many were sent."""
    if not configured():
        return 0
    sent = 0
    for j in db.list_jobs(status=["ready_for_review", "needs_attention"], order="score", limit=50):
        if any(e["event"] == "telegram_sent" for e in db.events_for(j["id"])):
            continue
        try:
            msg = call("sendMessage", chat_id=env("TELEGRAM_CHAT_ID"), text=_job_text(j), parse_mode="HTML",
                       disable_web_page_preview=True, reply_markup=_buttons(j))
        except Exception as e:
            log.warning("Telegram send failed: %s", e)
            break
        db.log_event(j["id"], "telegram_sent", str(msg.get("message_id")))
        sent += 1
    return sent


def send_text(text: str) -> None:
    if configured():
        try:
            call("sendMessage", chat_id=env("TELEGRAM_CHAT_ID"), text=text[:4000], disable_web_page_preview=True)
        except Exception as e:
            log.warning("Telegram send failed: %s", e)


def _offset_file() -> Path:
    return paths().data / "telegram_offset.txt"


def _handle_callback(db: DB, cq: dict) -> None:
    chat_id = str(((cq.get("message") or {}).get("chat") or {}).get("id", ""))
    if chat_id != str(env("TELEGRAM_CHAT_ID")):
        log.warning("Ignored a Telegram button press from another chat")
        return
    action, _, raw_id = (cq.get("data") or "").partition(":")
    reply = "Unknown action"
    try:
        job = db.get_job(int(raw_id))
    except ValueError:
        job = None
    if job and action == "approve":
        if job["status"] in APPROVABLE:
            db.set_status(job["id"], "approved", "approved in Telegram")
            reply = "Approved. It will be submitted on the next run if every answer is verified."
        else:
            reply = f"Not changed: the job is now '{job['status']}'."
    elif job and action == "skip":
        if job["status"] in SKIPPABLE:
            db.set_status(job["id"], "skipped", "skipped in Telegram")
            reply = "Skipped."
        else:
            reply = f"Not changed: the job is now '{job['status']}'."
    try:
        call("answerCallbackQuery", callback_query_id=cq["id"], text=reply[:190])
        msg = cq.get("message") or {}
        if msg.get("message_id") and job:
            call("editMessageText", chat_id=chat_id, message_id=msg["message_id"],
                 text=_job_text(db.get_job(job["id"])) + f"\n\n<i>{html.escape(reply)}</i>", parse_mode="HTML",
                 disable_web_page_preview=True)
    except Exception as e:
        log.warning("Telegram reply failed: %s", e)


def _handle_message(db: DB, m: dict) -> None:
    chat_id = str((m.get("chat") or {}).get("id", ""))
    if chat_id != str(env("TELEGRAM_CHAT_ID")):
        return
    text = (m.get("text") or "").strip().lower()
    if text in ("/status", "/start", "status"):
        c = db.overview()
        call("sendMessage", chat_id=chat_id, text=(
            f"Submitted: {c['applications_submitted']}\nReady for review: {c['ready_for_review']}\n"
            f"Needs attention: {c['needs_attention']}\nInterviews: {c['interviews']}\nDiscovered: {c['jobs_discovered']}"))


def process_updates(db: DB, wait_seconds: int = 0) -> int:
    """Read pending button presses and messages. Returns how many updates were handled."""
    if not configured():
        return 0
    f = _offset_file()
    offset = int(f.read_text()) if f.exists() else 0
    try:
        updates = call("getUpdates", offset=offset, timeout=wait_seconds, allowed_updates=["callback_query", "message"])
    except Exception as e:
        log.warning("Telegram getUpdates failed: %s", e)
        return 0
    for u in updates:
        try:
            if "callback_query" in u:
                _handle_callback(db, u["callback_query"])
            elif "message" in u:
                _handle_message(db, u["message"])
        except Exception:
            log.exception("Telegram update failed")
        offset = max(offset, u["update_id"] + 1)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(str(offset))
    return len(updates)


def listen_forever() -> None:
    """Long-poll Telegram so approvals register within seconds (run at logon by Task Scheduler)."""
    log.info("Telegram listener started")
    while True:
        db = DB()
        try:
            process_updates(db, wait_seconds=50)
        finally:
            db.close()
        time.sleep(1)


def find_chat_id() -> str | None:
    """After Anagha sends /start to the bot, return her chat ID from the pending updates."""
    updates = call("getUpdates", timeout=0)
    for u in reversed(updates):
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("type") == "private":
            return str(chat["id"])
    return None
