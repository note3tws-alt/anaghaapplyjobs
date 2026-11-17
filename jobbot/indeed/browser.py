"""Persistent, isolated browser session for Indeed.

- Uses its own profile folder (data/browser-profile), separate from Anagha's everyday Chrome.
- She signs in once by hand (`python -m jobbot login`); the session cookie stays in that folder.
- No passwords are stored or typed by the bot. No stealth tricks. CAPTCHA, login and other checks
  stop the run and notify her.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from jobbot.config import env, paths
from jobbot.indeed import selectors as S

log = logging.getLogger("jobbot.browser")


class PauseRequired(Exception):
    """Something needs a human: login, CAPTCHA or another security check."""

    def __init__(self, kind: str, url: str, detail: str = ""):
        super().__init__(f"{kind} at {url} {detail}".strip())
        self.kind, self.url, self.detail = kind, url, detail


def first(page_or_loc, selectors: list[str]):
    """First matching locator from a list of selectors, or None."""
    for sel in selectors:
        try:
            loc = page_or_loc.locator(sel)
            if loc.count() > 0:
                return loc.first
        except Exception:  # bad selector for this engine; try the next
            continue
    return None


def wait_first(page, selectors: list[str], timeout_ms: int = 8000):
    """Like first(), but gives content that loads after the page (such as the job description) time to appear."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        loc = first(page, selectors)
        if loc is not None or time.monotonic() >= deadline:
            return loc
        page.wait_for_timeout(500)


def text_of(page_or_loc, selectors: list[str]) -> str:
    loc = first(page_or_loc, selectors)
    if loc is None:
        return ""
    try:
        return (loc.inner_text(timeout=2000) or "").strip()
    except Exception:
        return ""


def detect_blocker(page) -> tuple[str, str] | None:
    url = page.url or ""
    if any(p in url for p in S.LOGIN_URL_PARTS):
        return "login", "Indeed is asking to sign in"
    if first(page, S.CAPTCHA) is not None:
        return "captcha", "Human verification is showing"
    try:
        title = page.title() or ""
        body = page.locator("body").inner_text(timeout=2000)[:3000]
    except Exception:
        title, body = "", ""
    if re.search(S.CAPTCHA_TEXT, f"{title}\n{body}", re.I):
        return "captcha", "Security check text on the page"
    return None


def check_blockers(page) -> None:
    b = detect_blocker(page)
    if b:
        raise PauseRequired(b[0], page.url, b[1])


def is_signed_in(page) -> bool:
    if first(page, S.SIGNED_IN) is not None:
        return True
    return first(page, S.SIGN_IN_LINK) is None and "indeed" in (page.url or "")


class BrowserSession:
    def __init__(self, settings: dict, *, headless: bool | None = None, profile_dir: Path | None = None,
                 pace_seconds: float | None = None):
        b = settings.get("browser", {})
        self.base_url = b.get("base_url", "https://ae.indeed.com").rstrip("/")
        self.channel = env("JOBBOT_BROWSER_CHANNEL", b.get("channel", "chrome"))
        self.headless = b.get("headless", False) if headless is None else headless
        pdir = profile_dir or b.get("profile_dir", "data/browser-profile")
        self.profile_dir = Path(pdir) if Path(pdir).is_absolute() else paths().root / pdir
        self.pace = settings.get("seconds_between_page_loads", 6) if pace_seconds is None else pace_seconds
        self._pw = self._ctx = None
        self.page = None
        self._last_load = 0.0
        self.pages_loaded = 0

    def __enter__(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        kwargs = dict(user_data_dir=str(self.profile_dir), headless=self.headless,
                      viewport={"width": 1280, "height": 900}, locale="en-AE", timezone_id="Asia/Dubai",
                      accept_downloads=False)
        exe = env("JOBBOT_BROWSER_EXECUTABLE")
        if exe:
            kwargs["executable_path"] = exe
        elif self.channel and self.channel != "chromium":
            kwargs["channel"] = self.channel
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(**kwargs)
        except Exception as e:
            if "channel" in kwargs:
                log.warning("Could not start %s (%s); falling back to Playwright Chromium", self.channel, e)
                kwargs.pop("channel")
                self._ctx = self._pw.chromium.launch_persistent_context(**kwargs)
            else:
                raise
        self._ctx.set_default_timeout(20000)
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    def goto(self, url: str, page=None):
        """Polite navigation: waits between page loads, then checks for login / CAPTCHA."""
        page = page or self.page
        wait = self.pace - (time.monotonic() - self._last_load)
        if wait > 0:
            time.sleep(wait)
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        self._last_load = time.monotonic()
        self.pages_loaded += 1
        check_blockers(page)
        return page

    def screenshot(self, name: str, page=None) -> str:
        page = page or self.page
        out = paths().screenshots / f"{time.strftime('%Y%m%d-%H%M%S')}_{re.sub(r'[^A-Za-z0-9_-]+', '-', name)[:60]}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(out), full_page=True)
        except Exception as e:
            log.warning("screenshot failed: %s", e)
            return ""
        return str(out)
