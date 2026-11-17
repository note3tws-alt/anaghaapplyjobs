import React, { useEffect, useMemo, useState } from "react";

const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.headers.get("content-type")?.includes("json") ? r.json() : r.text();
};

const TABS = ["Overview", "Opportunities", "Tracker", "Reports", "Settings"];

const STATUS_LABEL = {
  discovered: "Discovered", rejected: "Filtered out", possible: "Possible match", shortlisted: "Shortlisted",
  prepared: "Documents ready", ready_for_review: "Ready for review", approved: "Approved to submit",
  needs_attention: "Needs attention", external_apply: "Apply on employer site", submitted: "Submitted",
  interview: "Interview", offer: "Offer", rejected_by_employer: "Rejected by employer", withdrawn: "Withdrawn",
  skipped: "Skipped",
};
const STATUS_TONE = {
  submitted: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  interview: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
  offer: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
  ready_for_review: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  approved: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  needs_attention: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-300",
  external_apply: "bg-amber-50 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  rejected_by_employer: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
  rejected: "bg-slate-100 text-slate-600 dark:bg-neutral-800 dark:text-neutral-400",
};

function Badge({ status }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[status] || "bg-slate-100 text-slate-700 dark:bg-neutral-800 dark:text-neutral-300"}`}>
      {STATUS_LABEL[status] || status}
    </span>
  );
}

function ScorePill({ score }) {
  if (score == null) return <span className="text-slate-400">–</span>;
  const tone = score >= 80 ? "text-emerald-700 dark:text-emerald-400" : score >= 65 ? "text-blue-700 dark:text-blue-400" : score >= 50 ? "text-amber-700 dark:text-amber-400" : "text-slate-500";
  return <span className={`font-semibold tabular-nums ${tone}`}>{score}</span>;
}

function Stat({ label, value, hint }) {
  return (
    <div className="card">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-neutral-400">{label}</div>
      <div className="mt-1 text-3xl font-semibold tabular-nums">{value ?? "–"}</div>
      {hint && <div className="mt-1 text-xs text-slate-500 dark:text-neutral-400">{hint}</div>}
    </div>
  );
}

function DailyChart({ data }) {
  const [hover, setHover] = useState(null);
  if (!data?.length) return null;
  const max = Math.max(1, ...data.map((d) => Math.max(d.relevant, d.submitted)));
  const series = [["relevant", "Relevant found", "var(--series-1)"], ["submitted", "Submitted", "var(--series-2)"]];
  const step = Math.ceil(data.length / 7);
  return (
    <div>
      <div className="mb-2 flex gap-4 text-xs text-slate-600 dark:text-neutral-300">
        {series.map(([k, l, c]) => (
          <span key={k} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} />{l}</span>
        ))}
        <span className="ml-auto text-slate-400">max {max} / day</span>
      </div>
      <div className="relative flex h-40 items-end border-b border-slate-200 dark:border-neutral-700" role="img" aria-label="Relevant vacancies and submissions per day">
        {data.map((d, i) => (
          <div key={d.date} className="flex h-full flex-1 items-end justify-center gap-0.5 px-px hover:bg-slate-100/60 dark:hover:bg-neutral-800/60"
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            {series.map(([k, , c]) => (
              <div key={k} className="w-full max-w-3 rounded-t" style={{ height: `${(d[k] / max) * 100}%`, background: c, minHeight: d[k] ? 2 : 0 }} />
            ))}
          </div>
        ))}
        {hover != null && (
          <div className="pointer-events-none absolute top-0 z-10 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-md dark:border-neutral-700 dark:bg-neutral-800"
            style={{ left: `${Math.min(75, (hover / data.length) * 100)}%` }}>
            <div className="font-semibold">{data[hover].date}</div>
            <div>Discovered: {data[hover].discovered}</div>
            <div>Relevant found: {data[hover].relevant}</div>
            <div>Submitted: {data[hover].submitted}</div>
          </div>
        )}
      </div>
      <div className="flex text-[10px] text-slate-500 dark:text-neutral-400">
        {data.map((d, i) => <div key={d.date} className="flex-1 text-center">{i % step === 0 ? d.date.slice(5) : ""}</div>)}
      </div>
    </div>
  );
}

function Overview({ openJob }) {
  const [d, setD] = useState(null);
  const [attention, setAttention] = useState([]);
  useEffect(() => {
    api("/api/overview").then(setD);
    api("/api/jobs?view=tracker&status=needs_attention").then(setAttention);
  }, []);
  if (!d) return <p>Loading…</p>;
  const c = d.counts;
  const last = d.last_runs?.[0];
  return (
    <div className="space-y-4">
      <div className={`card ${d.auto_submit ? "border-emerald-300" : "border-blue-200"}`}>
        <div className="text-sm">
          Mode: <b>{d.mode === "auto" ? "Authorised auto-apply" : "Review mode"}</b>.{" "}
          {d.auto_submit ? "Applications that meet the authorised rules are submitted automatically." : `Nothing is submitted automatically (${d.auto_reason}). Jobs you approve are submitted on the next run.`}
        </div>
        {last && <div className="mt-1 text-xs text-slate-500 dark:text-neutral-400">Last run: {last.started_at?.replace("T", " ").slice(0, 16)} · {last.status} · {last.new_jobs} new · {last.submitted} submitted</div>}
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Jobs discovered" value={c.jobs_discovered} />
        <Stat label="Shortlisted" value={c.jobs_shortlisted} hint={`${c.possible_matches} possible`} />
        <Stat label="Submitted" value={c.applications_submitted} />
        <Stat label="Interviews" value={c.interviews} />
        <Stat label="Pending" value={c.pending_applications} hint={`${c.ready_for_review} to review`} />
        <Stat label="Rejections" value={c.rejections} />
      </div>
      <div className="card">
        <h3 className="mb-2 font-semibold">Last 14 days</h3>
        <DailyChart data={d.daily} />
      </div>
      {attention.length > 0 && (
        <div className="card">
          <h3 className="mb-2 font-semibold">Needs your attention</h3>
          <ul className="divide-y divide-slate-100 dark:divide-neutral-800">
            {attention.map((j) => (
              <li key={j.id} className="flex cursor-pointer items-center justify-between gap-3 py-2 hover:bg-slate-50 dark:hover:bg-neutral-800" onClick={() => openJob(j.id)}>
                <span><b>{j.title}</b> · {j.company}</span>
                <span className="text-xs text-amber-700 dark:text-amber-400">{(j.pending_questions || []).length} question(s)</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function JobTable({ rows, openJob, columns }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-slate-500">Nothing here yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead><tr>{columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
        <tbody className="divide-y divide-slate-100 dark:divide-neutral-800">
          {rows.map((j) => (
            <tr key={j.id} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-neutral-800/60" onClick={() => openJob(j.id)}>
              {columns.map((c) => <td key={c.key}>{c.render ? c.render(j) : j[c.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const jobLink = (j) => j.url ? <a href={j.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="text-blue-700 underline dark:text-blue-400">Open</a> : "";

function Opportunities({ openJob, refreshKey }) {
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState("relevant");
  const [q, setQ] = useState("");
  useEffect(() => {
    const st = { relevant: "", shortlisted: "shortlisted", possible: "possible", rejected: "rejected", all: "" }[filter];
    const min = filter === "relevant" ? "&min_score=50" : "";
    api(`/api/jobs?view=opportunities${st ? `&status=${st}` : ""}${min}${q ? `&q=${encodeURIComponent(q)}` : ""}`)
      .then((r) => setRows(filter === "relevant" ? r.filter((j) => j.status !== "rejected") : r));
  }, [filter, q, refreshKey]);
  return (
    <div className="card">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {["relevant", "shortlisted", "possible", "rejected", "all"].map((f) => (
          <button key={f} className={filter === f ? "btn-primary" : "btn"} onClick={() => setFilter(f)}>{f[0].toUpperCase() + f.slice(1)}</button>
        ))}
        <input className="input ml-auto max-w-xs" placeholder="Search company, title, location" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <JobTable rows={rows} openJob={openJob} columns={[
        { key: "score", label: "Score", render: (j) => <ScorePill score={j.score} /> },
        { key: "title", label: "Position", render: (j) => <div><div className="font-medium">{j.title}</div><div className="text-xs text-slate-500">{j.classification}</div></div> },
        { key: "company", label: "Company" },
        { key: "location", label: "Location" },
        { key: "salary", label: "Salary", render: (j) => j.salary || <span className="text-slate-400">Not shown</span> },
        { key: "status", label: "Status", render: (j) => <Badge status={j.status} /> },
        { key: "url", label: "Job link", render: jobLink },
      ]} />
    </div>
  );
}

function Tracker({ openJob, refreshKey }) {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  useEffect(() => { api(`/api/jobs?view=tracker${q ? `&q=${encodeURIComponent(q)}` : ""}`).then(setRows); }, [q, refreshKey]);
  return (
    <div className="card">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="font-semibold">Applications</h3>
        <input className="input ml-auto max-w-xs" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <JobTable rows={rows} openJob={openJob} columns={[
        { key: "application_date", label: "Applied / filled", render: (j) => (j.application_date || "").slice(0, 10) || "–" },
        { key: "company", label: "Company" },
        { key: "title", label: "Position" },
        { key: "status", label: "Status", render: (j) => <Badge status={j.status} /> },
        { key: "url", label: "Application URL", render: jobLink },
      ]} />
    </div>
  );
}

function Reports() {
  const [d, setD] = useState(null);
  const [sel, setSel] = useState(null);
  const [html, setHtml] = useState("");
  useEffect(() => { api("/api/reports").then((r) => { setD(r); if (r.daily[0]) setSel(["daily", r.daily[0]]); }); }, []);
  useEffect(() => { if (sel) api(`/api/reports/${sel[0]}/${sel[1]}`).then(setHtml).catch(() => setHtml("")); }, [sel]);
  if (!d) return <p>Loading…</p>;
  const totals = d.daily_stats.reduce((a, r) => ({ discovered: a.discovered + r.discovered, relevant: a.relevant + r.relevant, submitted: a.submitted + r.submitted }), { discovered: 0, relevant: 0, submitted: 0 });
  const week = d.daily_stats.slice(-7).reduce((a, r) => a + r.submitted, 0);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Discovered (28 days)" value={totals.discovered} />
        <Stat label="Relevant (28 days)" value={totals.relevant} />
        <Stat label="Submitted (28 days)" value={totals.submitted} />
        <Stat label="Submitted this week" value={week} />
      </div>
      <div className="card"><h3 className="mb-2 font-semibold">Daily performance (28 days)</h3><DailyChart data={d.daily_stats} /></div>
      <div className="grid gap-4 md:grid-cols-[220px_1fr]">
        <div className="card space-y-3 text-sm">
          {["daily", "weekly"].map((k) => (
            <div key={k}>
              <div className="mb-1 font-semibold capitalize">{k}</div>
              {d[k].length === 0 && <div className="text-slate-500">None yet</div>}
              {d[k].map((n) => (
                <button key={n} className={`block w-full rounded px-2 py-1 text-left ${sel?.[1] === n ? "bg-blue-50 font-medium text-blue-800 dark:bg-blue-900/40 dark:text-blue-200" : "hover:bg-slate-100 dark:hover:bg-neutral-800"}`} onClick={() => setSel([k, n])}>{n}</button>
              ))}
            </div>
          ))}
        </div>
        <div className="card min-h-64 overflow-hidden p-0">
          {html ? <iframe title="report" className="h-[70vh] w-full bg-white" srcDoc={html} sandbox="allow-popups allow-popups-to-escape-sandbox" /> : <p className="p-4 text-sm text-slate-500">Select a report.</p>}
        </div>
      </div>
    </div>
  );
}

function ListEditor({ label, items, onChange }) {
  const [txt, setTxt] = useState((items || []).join("\n"));
  useEffect(() => setTxt((items || []).join("\n")), [items]);
  return (
    <label className="block text-sm">
      <span className="font-medium">{label}</span>
      <textarea className="input mt-1 h-28 font-mono" value={txt} onChange={(e) => { setTxt(e.target.value); onChange(e.target.value.split("\n").map((s) => s.trim()).filter(Boolean)); }} />
    </label>
  );
}

function Settings() {
  const [s, setS] = useState(null);
  const [info, setInfo] = useState(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { api("/api/settings").then((r) => { setS(r.settings); setInfo(r); }); }, []);
  if (!s) return <p>Loading…</p>;
  const set = (k, v) => setS({ ...s, [k]: v });
  const num = (k, label, hint) => (
    <label className="block text-sm"><span className="font-medium">{label}</span>
      <input type="number" className="input mt-1" value={s[k]} onChange={(e) => set(k, Number(e.target.value))} />
      {hint && <span className="text-xs text-slate-500">{hint}</span>}
    </label>
  );
  const save = async () => {
    try {
      const r = await api("/api/settings", { method: "PUT", body: JSON.stringify(s) });
      setS(r.settings); setInfo(r); setMsg(r.note || "Saved.");
    } catch (e) { setMsg("Not saved: " + e.message); }
  };
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <div className="space-y-4">
      <div className="card text-sm">
        <b>Application mode:</b>{" "}
        <select className="input ml-2 inline-block w-auto" value={s.application_mode} onChange={(e) => set("application_mode", e.target.value)}>
          <option value="review">Review mode (prepare and fill, never submit)</option>
          <option value="auto" disabled={!s.authorisation?.authorised}>Authorised auto-apply</option>
        </select>
        <p className="mt-2 text-slate-600 dark:text-neutral-300">
          Auto-apply can only be switched on after Anagha runs <code>python -m jobbot authorise</code> and types her confirmation. Changing the rules below switches submission off again until she re-authorises. Current state: {info?.auto_reason}.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="card space-y-3">
          <h3 className="font-semibold">Matching and limits</h3>
          {num("match_threshold", "Job match threshold", "Prepare and apply at or above this score (65 = Good match)")}
          {num("review_threshold", "Possible-match threshold", "Shown for review, never auto-applied")}
          {num("daily_application_limit", "Daily application limit", "Target 5–10 when enough good vacancies exist")}
          {num("minimum_salary_aed", "Minimum salary (AED / month)", "0 = no minimum. Jobs without a salary are never rejected for salary")}
          {num("posted_within_days", "Only jobs posted in the last N days")}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!s.only_apply_in_search_locations} onChange={(e) => set("only_apply_in_search_locations", e.target.checked)} /> Reject jobs outside the search locations</label>
        </div>
        <div className="card space-y-3">
          <h3 className="font-semibold">Search</h3>
          <ListEditor label="Search locations (one per line)" items={s.locations} onChange={(v) => set("locations", v)} />
          {Object.entries(s.job_titles || {}).map(([cat, titles]) => (
            <ListEditor key={cat} label={`Job titles: ${cat.replace("_", " ")}`} items={titles} onChange={(v) => set("job_titles", { ...s.job_titles, [cat]: v })} />
          ))}
        </div>
        <div className="card space-y-3">
          <h3 className="font-semibold">Automation schedule (Asia/Dubai)</h3>
          <div className="flex flex-wrap gap-2">
            {days.map((d) => {
              const on = s.schedule.days.includes(d);
              return <button key={d} className={on ? "btn-primary" : "btn"} onClick={() => set("schedule", { ...s.schedule, days: on ? s.schedule.days.filter((x) => x !== d) : [...s.schedule.days, d] })}>{d}</button>;
            })}
          </div>
          <label className="block text-sm"><span className="font-medium">Time</span>
            <input type="time" className="input mt-1 w-40" value={s.schedule.time} onChange={(e) => set("schedule", { ...s.schedule, time: e.target.value })} />
          </label>
          <p className="text-xs text-slate-500">After changing the schedule, run <code>scripts\windows\register_task.ps1</code> again so Windows Task Scheduler picks it up. The computer must be on and signed in at that time.</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <button className="btn-primary" onClick={save}>Save settings</button>
        {msg && <span className="text-sm">{msg}</span>}
      </div>
    </div>
  );
}

function JobDrawer({ id, onClose, onChanged }) {
  const [j, setJ] = useState(null);
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState("");
  const load = () => api(`/api/jobs/${id}`).then((r) => { setJ(r); setNotes(r.notes || ""); });
  useEffect(() => { load(); }, [id]);
  if (!j) return null;
  const bd = j.score_breakdown || {};
  const setStatus = async (status) => {
    try { await api(`/api/jobs/${id}/status`, { method: "POST", body: JSON.stringify({ status }) }); setErr(""); await load(); onChanged(); }
    catch (e) { setErr(e.message); }
  };
  const actions = [
    ["approved", "Approve: submit on next run", ["ready_for_review", "prepared", "shortlisted", "possible", "needs_attention"]],
    ["skipped", "Skip this job", ["ready_for_review", "prepared", "shortlisted", "possible", "needs_attention", "approved", "external_apply"]],
    ["submitted", "I applied myself", ["needs_attention", "external_apply", "ready_for_review", "prepared", "shortlisted", "possible", "approved"]],
    ["interview", "Interview", ["submitted"]],
    ["offer", "Offer", ["submitted", "interview"]],
    ["rejected_by_employer", "Rejected by employer", ["submitted", "interview"]],
    ["withdrawn", "Withdrawn", ["submitted", "interview", "approved"]],
  ].filter(([, , from]) => from.includes(j.status));
  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-black/30" onClick={onClose}>
      <aside className="h-full w-full max-w-2xl overflow-y-auto bg-white p-5 shadow-xl dark:bg-neutral-900" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">{j.title}</h2>
            <div className="text-sm text-slate-600 dark:text-neutral-300">{j.company} · {j.location} {j.salary ? `· ${j.salary}` : ""}</div>
            <div className="mt-1 flex items-center gap-2"><Badge status={j.status} /> <ScorePill score={j.score} /> <span className="text-xs text-slate-500">{j.classification}</span></div>
          </div>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
        {j.reject_reason && <p className="mt-3 text-sm text-slate-600 dark:text-neutral-300">Reason: {j.reject_reason}</p>}
        <div className="mt-4 flex flex-wrap gap-2">
          {j.url && <a className="btn" href={j.url} target="_blank" rel="noreferrer">Open on Indeed</a>}
          {j.apply_url && <a className="btn" href={j.apply_url} target="_blank" rel="noreferrer">Employer site</a>}
          {j.has_cv && <a className="btn" href={`/api/jobs/${id}/file/cv`} target="_blank" rel="noreferrer">Tailored CV</a>}
          {j.has_letter && <a className="btn" href={`/api/jobs/${id}/file/letter`} target="_blank" rel="noreferrer">Cover letter</a>}
          {j.has_screenshot && <a className="btn" href={`/api/jobs/${id}/file/screenshot`} target="_blank" rel="noreferrer">Form screenshot</a>}
        </div>
        {actions.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {actions.map(([s, label]) => <button key={s} className={s === "approved" ? "btn-primary" : "btn"} onClick={() => setStatus(s)}>{label}</button>)}
          </div>
        )}
        {err && <p className="mt-2 text-sm text-rose-600">{err}</p>}
        {(j.pending_questions || []).length > 0 && (
          <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/40">
            <b>The bot stopped on these questions:</b>
            <ul className="mt-1 list-disc pl-5">{j.pending_questions.map((q, i) => <li key={i}>{q.question} <span className="text-xs text-slate-500">({q.reason})</span></li>)}</ul>
            <p className="mt-2 text-xs">Answer them yourself on Indeed, or add a verified answer in <code>config/screening_answers.yaml</code>, then approve again.</p>
          </div>
        )}
        {(j.flags || []).length > 0 && (
          <div className="mt-4 text-sm"><b>Things to check</b><ul className="list-disc pl-5">{j.flags.map((f, i) => <li key={i}>{f}</li>)}</ul></div>
        )}
        <h3 className="mt-5 font-semibold">Why this score</h3>
        <table className="mt-1 w-full">
          <tbody className="divide-y divide-slate-100 dark:divide-neutral-800">
            {Object.entries(bd).filter(([, v]) => v && typeof v === "object" && "points" in v).map(([k, v]) => (
              <tr key={k}><td className="capitalize">{k.replaceAll("_", " ")}</td><td className="tabular-nums">{v.points}/{v.max}</td><td className="text-slate-600 dark:text-neutral-300">{v.why}{v.missing?.length ? ` · not on CV: ${v.missing.join(", ")}` : ""}</td></tr>
            ))}
          </tbody>
        </table>
        {(bd.adjustments || []).length > 0 && <p className="mt-1 text-xs text-slate-500">Adjustments: {bd.adjustments.join(", ")}</p>}
        <h3 className="mt-5 font-semibold">Notes</h3>
        <textarea className="input mt-1 h-20" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <button className="btn mt-2" onClick={() => api(`/api/jobs/${id}/notes`, { method: "POST", body: JSON.stringify({ notes }) })}>Save note</button>
        {j.submission_confirmation && <p className="mt-4 text-sm"><b>Confirmation:</b> {j.submission_confirmation}</p>}
        <h3 className="mt-5 font-semibold">History</h3>
        <ul className="mt-1 space-y-1 text-xs text-slate-600 dark:text-neutral-300">
          {(j.events || []).filter((e) => e.event !== "apply_answers").map((e) => <li key={e.id}>{e.ts.replace("T", " ").slice(0, 16)} · {e.event.replace("status:", "")} {e.detail ? `· ${e.detail.slice(0, 140)}` : ""}</li>)}
        </ul>
        <details className="mt-5 text-sm"><summary className="cursor-pointer font-semibold">Job description</summary>
          <pre className="mt-2 whitespace-pre-wrap font-sans text-sm text-slate-700 dark:text-neutral-300">{j.description}</pre>
        </details>
      </aside>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState(() => { try { return localStorage.getItem("tab") || "Overview"; } catch { return "Overview"; } });
  const [job, setJob] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => { try { localStorage.setItem("tab", tab); } catch {} }, [tab]);
  const view = useMemo(() => ({
    Overview: <Overview openJob={setJob} key={refreshKey} />,
    Opportunities: <Opportunities openJob={setJob} refreshKey={refreshKey} />,
    Tracker: <Tracker openJob={setJob} refreshKey={refreshKey} />,
    Reports: <Reports />,
    Settings: <Settings />,
  }[tab]), [tab, refreshKey]);
  return (
    <div className="mx-auto max-w-7xl px-4 py-5">
      <header className="mb-4 flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-xl font-semibold text-[#1f3a5f] dark:text-blue-200">Anagha's Job Assistant</h1>
          <p className="text-xs text-slate-500 dark:text-neutral-400">Medical coding, insurance and RCM roles on Indeed UAE</p>
        </div>
        <nav className="ml-auto flex flex-wrap gap-1">
          {TABS.map((t) => <button key={t} className={tab === t ? "btn-primary" : "btn"} onClick={() => setTab(t)}>{t}</button>)}
        </nav>
      </header>
      {view}
      {job && <JobDrawer id={job} onClose={() => setJob(null)} onChanged={() => setRefreshKey((k) => k + 1)} />}
    </div>
  );
}
