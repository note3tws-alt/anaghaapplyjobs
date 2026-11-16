"""Walk an Indeed Apply form.

Review mode: fill what is verified, upload the tailored CV, stop on the final page without submitting.
Submit (only for jobs Anagha approved, or auto mode after she authorised the rules): same walk, then
click submit only if every answer on the way came from a verified source, and confirm the result.
Any unknown, legal, salary, sensitive or unverified work-authorisation question stops the walk.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field

from jobbot.indeed import selectors as S
from jobbot.indeed.browser import BrowserSession, PauseRequired, check_blockers, first
from jobbot.screening import CONTACT_FIELDS, Answerer

log = logging.getLogger("jobbot.apply")

MAX_STEPS = 12

COLLECT_FIELDS_JS = r"""
() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const labelFor = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return clean(l.innerText); }
    if (el.getAttribute('aria-label')) return clean(el.getAttribute('aria-label'));
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(' ').map(id => document.getElementById(id)).filter(Boolean).map(n => n.innerText).join(' '); if (t) return clean(t); }
    const fs = el.closest('fieldset'); if (fs) { const lg = fs.querySelector('legend'); if (lg) return clean(lg.innerText); }
    const wrap = el.closest('[data-testid*="question"], .ia-Questions-item, .question, div');
    if (wrap) { const l = wrap.querySelector('label, legend, h3, span'); if (l) return clean(l.innerText); }
    return clean(el.getAttribute('placeholder') || el.name || '');
  };
  const out = []; const seenRadio = new Set(); let n = 0;
  for (const el of document.querySelectorAll('input, select, textarea')) {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'file', 'search'].includes(type)) continue;
    if (!visible(el) && type !== 'radio' && type !== 'checkbox') continue;
    if (type === 'radio') {
      if (seenRadio.has(el.name)) continue; seenRadio.add(el.name);
      const radios = [...document.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)];
      const opts = radios.map(r => { const id = 'jb' + (n++); r.setAttribute('data-jobbot', id); return {id, text: labelFor(r) || r.value, checked: r.checked}; });
      const fs = el.closest('fieldset'); const lg = fs && fs.querySelector('legend');
      const wrap = el.closest('[data-testid*="question"], .ia-Questions-item, .question');
      const q = lg ? clean(lg.innerText) : (wrap ? clean((wrap.querySelector('label, legend, h3, span') || wrap).innerText).split(' Yes')[0] : el.name);
      out.push({kind: 'radio', label: q, options: opts, required: radios.some(r => r.required) || /\*|required/i.test(q)});
      continue;
    }
    const id = 'jb' + (n++); el.setAttribute('data-jobbot', id);
    const f = {id, kind: el.tagName === 'SELECT' ? 'select' : (el.tagName === 'TEXTAREA' ? 'textarea' : type),
               label: labelFor(el), required: el.required || el.getAttribute('aria-required') === 'true',
               value: el.type === 'checkbox' ? (el.checked ? 'checked' : '') : (el.value || '')};
    if (el.tagName === 'SELECT') f.options = [...el.options].filter(o => o.value !== '').map(o => clean(o.text));
    out.push(f);
  }
  return out;
}
"""


@dataclass
class ApplyResult:
    status: str                       # ready_for_review | submitted | needs_attention | external_apply
    detail: str = ""
    answered: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    screenshot: str = ""
    confirmation: str = ""
    cv_uploaded: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _is_contact(label: str) -> bool:
    ql = label.lower()
    return any(re.search(p, ql) for p in CONTACT_FIELDS.values()) and len(ql) < 60


def _visible(loc) -> bool:
    try:
        return loc is not None and loc.is_visible()
    except Exception:
        return False


def fill_fields(page, answerer: Answerer, result: ApplyResult) -> bool:
    """Fill every field on the current step. Returns False if anything needs Anagha."""
    ok = True
    for f in page.evaluate(COLLECT_FIELDS_JS):
        label = f.get("label") or ""
        if f["kind"] == "radio":
            opts = [o["text"] for o in f["options"]]
            ans = answerer.answer(label, opts)
            if not ans.ok:
                result.pending.append({"question": label, "options": opts, "reason": ans.reason})
                ok = False
                continue
            target = next(o for o in f["options"] if o["text"] == ans.answer)
            page.locator(f"[data-jobbot='{target['id']}']").check(force=True)
            result.answered.append({"question": label, "answer": ans.answer, "source": ans.rule})
            continue
        loc = page.locator(f"[data-jobbot='{f['id']}']")
        current = (f.get("value") or "").strip()
        if current and _is_contact(label) and f["kind"] not in ("checkbox",):
            result.answered.append({"question": label, "answer": current, "source": "prefilled by Indeed account"})
            continue
        if f["kind"] == "checkbox":
            ans = answerer.answer(label)
            if not ans.ok:
                result.pending.append({"question": label, "reason": ans.reason})
                ok = False
            elif ans.answer.lower() in ("yes", "true", "checked"):
                loc.check(force=True)
                result.answered.append({"question": label, "answer": "checked", "source": ans.rule})
            continue
        ans = answerer.answer(label, f.get("options"))
        if not ans.ok:
            if not current and not f.get("required") and not label:
                continue
            result.pending.append({"question": label, "options": f.get("options"), "reason": ans.reason})
            ok = False
            continue
        if f["kind"] == "select":
            loc.select_option(label=ans.answer)
        else:
            loc.fill(ans.answer)
        result.answered.append({"question": label, "answer": ans.answer, "source": ans.rule})
    return ok


def upload_cv(page, cv_path: str, result: ApplyResult) -> None:
    inp = first(page, S.APPLY_FILE_INPUT)
    if inp is None:
        opt = first(page, S.APPLY_UPLOAD_OPTION)
        if _visible(opt):
            opt.click()
            time.sleep(1)
            inp = first(page, S.APPLY_FILE_INPUT)
    if inp is not None:
        inp.set_input_files(cv_path)
        result.cv_uploaded = True
        time.sleep(1.5)


def open_apply_form(session: BrowserSession, job_url: str):
    page = session.goto(job_url)
    btn = first(page, S.INDEED_APPLY_BUTTON)
    if btn is None:
        return None
    try:
        with session._ctx.expect_page(timeout=6000) as newp:
            btn.click()
        form = newp.value
    except Exception:
        form = page  # opened in the same tab
    form.wait_for_load_state("domcontentloaded")
    check_blockers(form)
    return form


def run_apply(session: BrowserSession, job: dict, cv_path: str, answerer: Answerer, *, submit: bool) -> ApplyResult:
    result = ApplyResult(status="needs_attention")
    if job.get("apply_type") == "external":
        result.status, result.detail = "external_apply", "Employer's own website: apply by hand"
        return result
    form = open_apply_form(session, job["url"])
    if form is None:
        result.status, result.detail = "external_apply", "No Indeed Apply button found"
        return result
    name = f"job{job.get('id')}"
    for step in range(MAX_STEPS):
        check_blockers(form)
        try:
            form.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        body = form.locator("body").inner_text(timeout=5000)
        if re.search(S.APPLY_CONFIRMATION_TEXT, body, re.I):
            result.status, result.confirmation = "submitted", _confirmation_snippet(body)
            result.detail = "Indeed shows this application as already submitted"
            result.screenshot = session.screenshot(name + "-already", form)
            return result
        if result.cv_uploaded is False and first(form, S.APPLY_FILE_INPUT + S.APPLY_UPLOAD_OPTION[:1]) is not None:
            upload_cv(form, cv_path, result)
        submit_btn = first(form, S.APPLY_SUBMIT)
        if not fill_fields(form, answerer, result):
            result.status = "needs_attention"
            result.detail = f"{len(result.pending)} question(s) need Anagha's answer"
            result.screenshot = session.screenshot(name + "-questions", form)
            return result
        if _visible(submit_btn):
            result.screenshot = session.screenshot(name + "-review", form)
            if not submit:
                result.status, result.detail = "ready_for_review", "Filled up to the final page; not submitted"
                return result
            if result.pending:
                result.status, result.detail = "needs_attention", "Unverified answers; not submitted"
                return result
            submit_btn.click()
            try:
                form.wait_for_function(
                    "re => new RegExp(re, 'i').test(document.body.innerText)", arg=S.APPLY_CONFIRMATION_TEXT,
                    timeout=25000)
            except Exception:
                check_blockers(form)
                result.status = "needs_attention"
                result.detail = "Submit was clicked but no confirmation appeared; check Indeed > My jobs"
                result.screenshot = session.screenshot(name + "-unconfirmed", form)
                return result
            body = form.locator("body").inner_text()
            result.status, result.confirmation = "submitted", _confirmation_snippet(body)
            result.detail = "Submitted and confirmed by Indeed"
            result.screenshot = session.screenshot(name + "-submitted", form)
            return result
        cont = first(form, S.APPLY_CONTINUE)
        if not _visible(cont):
            result.detail = "Unrecognised application page"
            result.screenshot = session.screenshot(name + "-unknown", form)
            return result
        before = form.url + str(len(body))
        cont.click()
        time.sleep(1.5)
        after_body = form.locator("body").inner_text(timeout=5000)
        if re.search(S.APPLY_ERROR_TEXT, after_body, re.I) and (form.url + str(len(after_body))) == before:
            result.detail = "Indeed rejected a field on this step"
            result.screenshot = session.screenshot(name + "-error", form)
            return result
    result.detail = "Too many steps in the application form"
    return result


def _confirmation_snippet(body: str) -> str:
    m = re.search(S.APPLY_CONFIRMATION_TEXT, body, re.I)
    if not m:
        return ""
    return re.sub(r"\s+", " ", body[max(0, m.start() - 80): m.end() + 160]).strip()
