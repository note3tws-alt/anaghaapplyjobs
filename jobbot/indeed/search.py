"""Read Indeed search results and vacancy pages through the normal website, like a person browsing."""
from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from jobbot.indeed import selectors as S
from jobbot.indeed.browser import BrowserSession, first, text_of
from jobbot.sanitize import clean_field, clean_text

log = logging.getLogger("jobbot.search")


def search_url(base: str, query: str, location: str, days: int = 7, start: int = 0) -> str:
    params = {"q": query, "l": location, "fromage": str(days), "sort": "date"}
    if start:
        params["start"] = str(start)
    return f"{base}/jobs?{urlencode(params)}"


def job_url(base: str, jk: str) -> str:
    return f"{base}/viewjob?{urlencode({'jk': jk})}"


def job_key_from_url(url: str) -> str:
    q = parse_qs(urlparse(url).query)
    for k in ("jk", "vjk"):
        if q.get(k):
            return f"indeed-{q[k][0]}"
    return "url-" + hashlib.sha1(url.encode()).hexdigest()[:16]


def parse_results(page, base: str) -> list[dict]:
    cards = []
    card_sel = None
    for sel in S.SEARCH_CARD:
        if page.locator(sel).count():
            card_sel = sel
            break
    if not card_sel:
        return cards
    for card in page.locator(card_sel).all():
        link = first(card, S.CARD_LINK)
        if link is None:
            continue
        jk = link.get_attribute("data-jk") or ""
        href = link.get_attribute("href") or ""
        if not jk:
            jk = (parse_qs(urlparse(href).query).get("jk") or [""])[0]
        url = job_url(base, jk) if jk else urljoin(base + "/", href)
        cards.append({
            "job_key": f"indeed-{jk}" if jk else job_key_from_url(url),
            "jk": jk,
            "url": url,
            "title": clean_field(text_of(card, S.CARD_TITLE) or link.inner_text()),
            "company": clean_field(text_of(card, S.CARD_COMPANY)),
            "location": clean_field(text_of(card, S.CARD_LOCATION)),
            "salary": clean_field(text_of(card, S.CARD_SALARY)) if re.search(r"aed|\d", text_of(card, S.CARD_SALARY), re.I) else "",
            "easy_apply": first(card, S.CARD_EASY_APPLY) is not None,
        })
    return cards


def search(session: BrowserSession, query: str, location: str, days: int, pages: int = 1) -> list[dict]:
    found = []
    for i in range(pages):
        session.goto(search_url(session.base_url, query, location, days, start=i * 10))
        batch = parse_results(session.page, session.base_url)
        log.info("search %r in %s page %d: %d results", query, location, i + 1, len(batch))
        for b in batch:
            b["search_term"] = f"{query} | {location}"
        found += batch
        if len(batch) < 10:
            break
    return found


def read_job(session: BrowserSession, url: str) -> dict:
    page = session.goto(url)
    desc_loc = first(page, S.JOB_DESCRIPTION)
    description = clean_text(desc_loc.inner_html()) if desc_loc is not None else ""
    if first(page, S.INDEED_APPLY_BUTTON) is not None:
        apply_type = "indeed_apply"
    elif first(page, S.EXTERNAL_APPLY) is not None:
        apply_type = "external"
    else:
        apply_type = "unknown"
    ext = first(page, S.EXTERNAL_APPLY)
    return {
        "title": clean_field(text_of(page, S.JOB_TITLE)),
        "company": clean_field(text_of(page, S.JOB_COMPANY)),
        "location": clean_field(text_of(page, S.JOB_LOCATION)),
        "salary": clean_field(text_of(page, S.JOB_SALARY)),
        "description": description,
        "apply_type": apply_type,
        "apply_url": (ext.get_attribute("href") if ext is not None and apply_type == "external" else None),
    }
