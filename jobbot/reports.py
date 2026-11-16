"""Daily and weekly reports (Markdown + HTML) in reports/daily and reports/weekly."""
from __future__ import annotations

import html
from datetime import datetime, timedelta
from pathlib import Path

from jobbot.config import paths
from jobbot.db import DB, DUBAI


def _link(title: str, url: str | None) -> str:
    return f"[{title}]({url})" if url else title


def _md_to_html(md: str, title: str) -> str:
    out, in_list, in_table = [], False, False
    import re
    for line in md.splitlines():
        esc = html.escape(line)
        esc = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', esc)
        esc = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", esc)
        if line.startswith("|"):
            cells = [c.strip() for c in esc.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if not in_table:
                out.append("<table>"); in_table = True
                out.append("<tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr>")
            else:
                out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>"); in_table = False
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{esc[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>"); in_list = False
        if line.startswith("### "):
            out.append(f"<h3>{esc[4:]}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{esc[3:]}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{esc[2:]}</h1>")
        elif line.strip():
            out.append(f"<p>{esc}</p>")
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")
    css = ("body{font-family:Segoe UI,Arial,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1f2937}"
           "table{border-collapse:collapse;width:100%;margin:8px 0}td,th{border:1px solid #e5e7eb;padding:6px 8px;"
           "text-align:left;font-size:14px}th{background:#f3f4f6}h1{color:#1f3a5f}a{color:#1d4ed8}")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{css}</style></head><body>{''.join(out)}</body></html>"


def daily_markdown(db: DB, stats, day: str) -> str:
    jobs_today = [j for j in db.list_jobs(order="recent", limit=1000)
                  if (j.get("date_discovered") or "").startswith(day) or j["id"] in stats.touched_job_ids]
    submitted = [j for j in jobs_today if j["status"] in ("submitted",) and (j.get("application_date") or "").startswith(day)]
    review = [j for j in db.list_jobs(status="ready_for_review", order="score")]
    attention = [j for j in db.list_jobs(status="needs_attention", order="recent")]
    external = [j for j in db.list_jobs(status="external_apply", order="score", limit=30)]
    relevant = [j for j in jobs_today if j["status"] not in ("rejected", "discovered")]
    md = [f"# Daily job report: {day}", "",
          f"Mode: **{stats.mode}**" + (f" (auto-submit off: {stats.auto_reason})" if stats.mode == "review" or "not" in (stats.auto_reason or "") else ""),
          ""]
    if stats.paused:
        md += [f"**The run paused and needs Anagha:** {stats.paused}. Open the bot's browser with "
               "`python -m jobbot login`, complete the step yourself, then run again.", ""]
    md += ["## Summary", "",
           "| Measure | Count |", "|---|---|",
           f"| Vacancies seen in searches | {stats.found} |",
           f"| New vacancies read | {stats.new_jobs} |",
           f"| Relevant vacancies (score 50+) | {stats.relevant} |",
           f"| Applications prepared | {stats.prepared} |",
           f"| Filled and waiting for review | {stats.ready_for_review} |",
           f"| Applications submitted (confirmed) | {stats.submitted} |",
           f"| Need Anagha's attention | {stats.needs_attention} |",
           f"| Employer-site applications (apply by hand) | {stats.external} |", ""]
    md += ["## Applications submitted today", ""]
    md += [f"- {_link(j['title'], j['url'])} at **{j['company']}** (score {j['score']}). Confirmation: {j.get('submission_confirmation') or 'n/a'}"
           for j in submitted] or ["- None"]
    md += ["", "## Waiting for Anagha's review (filled, not submitted)", ""]
    md += [f"- {_link(j['title'], j['url'])} at **{j['company']}**, {j['location']} (score {j['score']})" for j in review] or ["- None"]
    md += ["", "## Needs attention", ""]
    for j in attention:
        qs = j.get("pending_questions") or []
        qtxt = "; ".join(f"\"{q.get('question')}\" ({q.get('reason')})" for q in qs) if isinstance(qs, list) else ""
        md.append(f"- {_link(j['title'], j['url'])} at **{j['company']}**: {qtxt or 'see dashboard'}")
    if not attention:
        md.append("- None")
    md += ["", "## Apply on the employer's website", ""]
    md += [f"- {_link(j['title'], j.get('apply_url') or j['url'])} at **{j['company']}** (score {j['score']})" for j in external] or ["- None"]
    md += ["", "## Relevant vacancies found today", "",
           "| Score | Match | Position | Company | Location | Salary |", "|---|---|---|---|---|---|"]
    for j in sorted(relevant, key=lambda x: -(x.get("score") or 0)):
        md.append(f"| {j['score']} | {j.get('classification') or ''} | {_link(j['title'], j['url'])} | {j['company']} | {j['location']} | {j.get('salary') or ''} |")
    md += ["", "## Rejected vacancies and reasons", ""]
    md += [f"- {_link(r['title'] or '?', r.get('url'))} at {r.get('company') or '?'} (score {r['score']}): {r['reason']}"
           for r in stats.rejected] or ["- None"]
    md += ["", "## Companies applied to today", ""]
    md += [f"- {c}" for c in sorted({j['company'] for j in submitted if j.get('company')})] or ["- None"]
    md += ["", "## Technical errors", ""]
    md += [f"- {e}" for e in stats.errors] or ["- None"]
    return "\n".join(md) + "\n"


def write_daily(db: DB, stats) -> Path:
    day = datetime.now(DUBAI).date().isoformat()
    folder = paths().reports / "daily"
    folder.mkdir(parents=True, exist_ok=True)
    md = daily_markdown(db, stats, day)
    out = folder / f"{day}.md"
    if out.exists():  # several runs in one day: keep each
        out = folder / f"{day}_run{stats.run_id}.md"
    out.write_text(md, encoding="utf-8")
    out.with_suffix(".html").write_text(_md_to_html(md, f"Daily report {day}"), encoding="utf-8")
    return out


def write_weekly(db: DB, end: datetime | None = None) -> Path:
    end = (end or datetime.now(DUBAI)).date()
    start = end - timedelta(days=6)
    rows = [r for r in db.daily_stats(days=7)]
    jobs = [j for j in db.list_jobs(order="recent", limit=5000) if start.isoformat() <= (j["date_discovered"] or "")[:10] <= end.isoformat()]
    applied = [j for j in db.list_jobs(status=["submitted", "interview", "offer", "rejected_by_employer"], order="applied", limit=5000)
               if start.isoformat() <= (j.get("application_date") or "")[:10] <= end.isoformat()]
    iso = end.isocalendar()
    md = [f"# Weekly job report: {start} to {end}", "", "## Daily performance", "",
          "| Date | Discovered | Relevant | Submitted |", "|---|---|---|---|"]
    md += [f"| {r['date']} | {r['discovered']} | {r['relevant']} | {r['submitted']} |" for r in rows]
    by_status: dict[str, int] = {}
    for j in jobs:
        by_status[j["status"]] = by_status.get(j["status"], 0) + 1
    md += ["", "## Application statistics", "", "| Status | Jobs |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in sorted(by_status.items(), key=lambda x: -x[1])]
    md += ["", f"Total discovered: **{len(jobs)}**. Submitted this week: **{len(applied)}**.", "",
           "## Applications submitted this week", ""]
    md += [f"- {(j.get('application_date') or '')[:10]}: {_link(j['title'], j['url'])} at **{j['company']}** ({j['status']})" for j in applied] or ["- None"]
    folder = paths().reports / "weekly"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{iso[0]}-W{iso[1]:02d}.md"
    text = "\n".join(md) + "\n"
    out.write_text(text, encoding="utf-8")
    out.with_suffix(".html").write_text(_md_to_html(text, f"Weekly report {iso[0]}-W{iso[1]:02d}"), encoding="utf-8")
    return out
