# Anagha's Job Assistant (jobbot)

An assistant that finds Medical Coding, Medical Insurance and Billing/RCM vacancies on **Indeed UAE**, scores
them against Anagha P's CV, writes a tailored CV and cover letter for each good match, fills the Indeed Apply
form, and records everything in a local database with a dashboard and daily reports.

It runs on Anagha's own Windows PC, **Monday to Saturday at 9:00 AM UAE time** (no Sunday run), and only
looks at **Dubai** vacancies. Both can be changed in the dashboard.

> **Safety defaults.** It starts in **review mode**: forms are filled up to the final page but never submitted.
> A job is submitted only when Anagha approves it (dashboard or Telegram), or after she switches on
> auto-apply herself with `python -m jobbot authorise`. It never types passwords, never solves or bypasses a
> CAPTCHA, sign-in or security check (it stops and tells her), and never invents experience.

## What happens on each run

1. Opens Indeed UAE in the bot's own Chrome profile, where Anagha signed in once herself.
2. Searches each job title (Medical Coding first) for Dubai, posted in the last 7 days.
3. Opens new vacancies and extracts title, company, location, salary, experience, education,
   certifications, skills and responsibilities. Already-known jobs are skipped (job ID, URL, or company + title).
4. Scores each job 0-100: coding relevance 25, CPC relevance 20, experience 20, skills 15, education 10,
   location 10. 80+ Excellent, 65-79 Good, 50-64 Possible, below 50 rejected (with the reason saved).
   Jobs asking for about one year are not rejected; employers that welcome CPC-certified freshers get a bonus.
5. For the best matches (up to the daily limit, default 8) it writes a tailored CV and cover letter
   (PDF and Word) into `data/applications/<date>_<company>_<title>/`.
6. Fills the Indeed Apply form: uploads the tailored CV and answers only questions it has a **verified**
   answer for. It stops for unknown questions, legal declarations, terms/consent, salary, sensitive personal
   data and unverified work-authorisation questions.
7. Review mode: stops on the final page and marks the job *Ready for review*. Approved jobs, or auto mode
   after authorisation: clicks submit, then waits for Indeed's confirmation text and records it.
8. Writes `reports/daily/<date>.md` and `.html` (weekly report on Saturdays), and sends email / Telegram
   notifications if configured.

## Quick start on Windows

```powershell
# in the project folder
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -CvPath "C:\path\to\Anagha_P_CV.pdf"
# sign in to Indeed once (desktop shortcut "Job Assistant - Sign in to Indeed" does the same)
.venv\Scripts\python.exe -m jobbot login
# safe rehearsal against an offline imitation of Indeed (nothing is sent anywhere)
.venv\Scripts\python.exe -m jobbot demo
# schedule Mon-Sat 9:00 AM Dubai time (add -Telegram if you set up Telegram approvals)
powershell -ExecutionPolicy Bypass -File scripts\windows\register_task.ps1
# open the dashboard (desktop shortcut "Job Assistant Dashboard")
.venv\Scripts\python.exe -m jobbot dashboard --open
```

Full instructions: **[docs/SETUP_AND_OPERATION.md](docs/SETUP_AND_OPERATION.md)**.
What was tested and what still needs testing on her PC: **[docs/TESTING.md](docs/TESTING.md)**.

## Commands

| Command | What it does |
|---|---|
| `python -m jobbot init --cv <pdf>` | Create local config, database and folders; read contact details from the CV |
| `python -m jobbot login` | Open the bot's browser so Anagha can sign in to Indeed herself |
| `python -m jobbot run` | One full run now (the scheduler uses `run --scheduled`) |
| `python -m jobbot demo` | Rehearsal against the offline mock site, in a throwaway folder |
| `python -m jobbot dashboard --open` | Dashboard on http://127.0.0.1:8765 (this PC only) |
| `python -m jobbot apply --job <id>` | Fill one job now in a visible window (add `--submit` for an approved job) |
| `python -m jobbot authorise` / `revoke` | Anagha switches authorised auto-apply on / off |
| `python -m jobbot telegram-setup` / `telegram` | Connect Telegram approvals / run the listener |
| `python -m jobbot import-jobs <file.json>` | Score and prepare vacancies from a JSON list (no browsing) |
| `python -m jobbot report [--weekly]`, `backup`, `status`, `doctor [--live]` | Reports, backups, health checks |

## Project layout

```
config/            settings.example.yaml, candidate_profile.yaml (verified CV facts), screening answers
jobbot/            Python package: extractor, scorer, documents, ai, screening, db, pipeline, reports,
                   notify, telegram_bot, indeed/ (browser, search, apply, selectors), dashboard/ (FastAPI)
frontend/          React + Tailwind dashboard source (built copy is in jobbot/dashboard/static)
scripts/windows/   install, Task Scheduler registration, run, login and dashboard launchers
tests/             pytest suite, fixtures from real Indeed UAE listings, offline mock of Indeed
data/ (local)      database, backups, tailored documents, screenshots, logs, browser profile (gitignored)
reports/ (local)   daily/ and weekly/ reports (gitignored)
```
