"""Notifications: optional email (only when fully configured) and a desktop alert on Windows."""
from __future__ import annotations

import logging
import platform
import smtplib
import subprocess
from email.message import EmailMessage
from pathlib import Path

from jobbot.config import env, paths

log = logging.getLogger("jobbot.notify")

EMAIL_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM", "EMAIL_TO")


def email_status() -> tuple[bool, str]:
    if str(env("EMAIL_ENABLED", "false")).lower() != "true":
        return False, "email is off (set EMAIL_ENABLED=true in .env)"
    missing = [k for k in EMAIL_KEYS if not env(k)]
    if missing:
        return False, "missing in .env: " + ", ".join(missing)
    return True, "configured"


def send_email(subject: str, text: str, html: str | None = None) -> bool:
    ok, why = email_status()
    if not ok:
        log.info("Email not sent: %s", why)
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, env("EMAIL_FROM"), env("EMAIL_TO")
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(env("SMTP_HOST"), int(env("SMTP_PORT", 587)), timeout=30) as s:
            s.starttls()
            s.login(env("SMTP_USER"), env("SMTP_PASSWORD"))
            s.send_message(msg)
        return True
    except Exception as e:
        log.error("Email failed: %s", e)
        return False


def desktop_alert(title: str, message: str) -> None:
    attention = paths().data / "ATTENTION.txt"
    attention.parent.mkdir(parents=True, exist_ok=True)
    attention.write_text(f"{title}\n\n{message}\n", encoding="utf-8")
    if platform.system() != "Windows":
        return
    t = title.replace("'", "''")[:60]
    m = message.replace("'", "''")[:240]
    ps = ("Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; "
          "$n.Icon=[System.Drawing.SystemIcons]::Information; $n.Visible=$true; "
          f"$n.ShowBalloonTip(15000,'{t}','{m}',[System.Windows.Forms.ToolTipIcon]::Info); Start-Sleep -s 16; $n.Dispose()")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        log.warning("desktop alert failed: %s", e)


def after_run(stats, report_path: Path) -> None:
    head = (f"{stats.submitted} submitted, {stats.ready_for_review} ready for review, "
            f"{stats.needs_attention} need attention, {stats.relevant} relevant found")
    if stats.paused:
        desktop_alert("Job bot paused: action needed", f"{stats.paused}. Run 'python -m jobbot login' and finish the step.")
    elif stats.ready_for_review or stats.needs_attention:
        desktop_alert("Job applications to review", head)
    try:
        md = Path(report_path).read_text(encoding="utf-8")
        html = Path(report_path).with_suffix(".html").read_text(encoding="utf-8")
    except OSError:
        md, html = head, None
    send_email(f"Job bot report: {head}", md, html)
    from jobbot import telegram_bot
    telegram_bot.send_text(f"Job bot run finished: {head}." + (f"\nPAUSED: {stats.paused}" if stats.paused else ""))
