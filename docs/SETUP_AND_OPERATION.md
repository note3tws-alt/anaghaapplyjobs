# Setup and daily operation

## 1. What you need

- Anagha's Windows 10/11 PC, switched on and signed in at 9:00 AM UAE time, Monday to Saturday.
  Sleep is fine (the task wakes the PC if "Allow wake timers" is on in Power Options), but the PC must not be
  shut down, and Windows must be signed in, because the bot uses a visible browser window in her session.
- Python 3.10 or newer from python.org (tick "Add python.exe to PATH" when installing).
- Google Chrome (recommended). Without it, the installer downloads Playwright's Chromium.
- Her CV PDF (`Anagha_P_CV.pdf`).

> If you later prefer cloud scheduling: a cloud machine does not share her PC's Indeed sign-in. It would need
> its own browser sign-in and would meet more Indeed security checks. Running on her PC is the supported setup.

## 2. Install (once)

Open PowerShell in the project folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -CvPath "C:\Users\<user>\Downloads\Anagha_P_CV.pdf"
```

This creates `.venv`, installs packages, creates `config\settings.yaml`, `config\screening_answers.yaml`,
`config\candidate_private.yaml` and `.env` from the examples, reads her email/phone/LinkedIn/AAPC ID from the
CV into `config\candidate_private.yaml`, checks the CV against `config\candidate_profile.yaml`, restricts
`data\` and the private config files to her Windows account, and adds two desktop shortcuts.

## 3. Sign in to Indeed (once, and whenever Indeed signs her out)

Double-click **Job Assistant - Sign in to Indeed** (or run `.venv\Scripts\python.exe -m jobbot login`).
A Chrome window opens on Indeed UAE using the bot's own profile folder (`data\browser-profile`), separate
from her everyday Chrome. Anagha signs in herself, including any email code or verification. The window
closes when she is signed in. The password is never stored by the bot.

## 4. Check the screening answers

Open `config\screening_answers.yaml`. The bot answers a question only when it matches a rule with
`verified: true`. Shipped answers come from the CV (CPC: Yes, lives in UAE: Yes, Bachelor's degree: Yes,
Arabic: No, English: Yes, nationality: Indian, eClaimLink: Yes).

Left unverified on purpose (the bot stops and asks):

- **Work authorisation / visa / sponsorship.** The CV says *Visit Visa*. Only Anagha can answer these.
- Years of coding / RCM experience (internship vs paid work is her call).
- Notice period, driving licence, DHA/DOH licence.

Always stop, whatever the file says: legal declarations, terms/consent, salary, and sensitive data
(passport, Emirates ID, date of birth, bank details and similar).

## 5. Rehearse safely

```powershell
.venv\Scripts\python.exe -m jobbot demo
```

Runs the full workflow against an offline imitation of Indeed in a temporary folder. It shows the browser
filling forms and stopping on questions. Nothing is sent to Indeed. It ends by printing how many submissions
were made to the mock site (review mode: 0).

Then do one real run in review mode while watching:

```powershell
.venv\Scripts\python.exe -m jobbot doctor --live   # checks sign-in and that Indeed's page layout is recognised
.venv\Scripts\python.exe -m jobbot run
```

## 6. Schedule it

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\register_task.ps1            # add -Telegram for approvals
```

Creates the task **AnaghaJobBot Run**, Monday-Saturday at 9:00 AM Dubai time (converted automatically if
the PC uses another time zone). The program also checks the Dubai day itself and does nothing on Sunday.
Run the script again after changing the schedule in the dashboard. Remove with `unregister_task.ps1`.

## 7. Every day

- After each run, a desktop notification appears if anything needs her, and `reports\daily\<date>.html` is written.
- Open the **Job Assistant Dashboard** shortcut:
  - **Overview**: counts, last run, 14-day chart, jobs needing attention.
  - **Opportunities**: every vacancy with score, salary, location and link. Click one to see why it scored
    as it did, the tailored CV and cover letter, a screenshot of the filled form, and its history.
  - **Tracker**: applications and their status. Mark *Interview*, *Offer*, *Rejected by employer* here.
  - **Reports**: daily and weekly reports and a 28-day chart.
  - **Settings**: locations, job titles, minimum salary, match threshold, daily limit, schedule, mode.
- For each *Ready for review* job: check it, then **Approve** (submitted on the next run, if every answer
  is verified) or **Skip**. To submit right away instead: `python -m jobbot apply --job <id> --submit`.
- *Needs attention* jobs list the questions the bot would not answer. Answer them on Indeed yourself, or add a
  verified rule to `config\screening_answers.yaml` and approve again.
- *Apply on employer site* jobs use the employer's own website; the bot leaves those to her (tailored CV and
  cover letter are ready in the job's folder).

## 8. Telegram approvals (optional)

1. In Telegram, open **@BotFather**, send `/newbot`, follow the steps, and copy the token.
2. Put it in `.env` as `TELEGRAM_BOT_TOKEN=...` (never paste it in a chat or commit it).
3. Open the new bot in Telegram and send `/start`.
4. Run `.venv\Scripts\python.exe -m jobbot telegram-setup`. It saves her chat ID and sends a test message.
5. Run `register_task.ps1 -Telegram` so the listener starts whenever she signs in to Windows.

After each run, every filled application arrives with **Approve** and **Skip** buttons. Only her chat is
obeyed. Approved jobs are submitted on the next run. Sending `/status` to the bot returns today's counts.

## 9. Authorised auto-apply (only when Anagha decides)

Leave review mode until she has watched several runs. When she is satisfied:

```powershell
.venv\Scripts\python.exe -m jobbot authorise
```

It prints the rules (locations, minimum score, daily limit, minimum salary, every verified answer) and she
types `I AUTHORISE`. From then on, jobs that meet the rules are submitted without per-job approval, but every
stop rule still applies, and each submission is confirmed against Indeed's confirmation text. Changing any
rule or answer switches submission off until she authorises again. `python -m jobbot revoke` switches it off.

## 10. Optional extras

- **AI writing (paid, off by default)**: everything else in this project is free. AI-written text needs a
  Claude API key, which is billed per use and is **not** included in a Claude Pro subscription. Without a key
  (the default) the built-in templates are used, still tailored per job. To turn it on, put the key in `.env`
  (`ANTHROPIC_API_KEY`). The summary and cover letter are then
  written by Claude from the verified CV facts and the job posting, with a server-side fallback model if the
  first one declines. Every AI text goes through a fact check (no invented years, certifications, licences,
  employers, grades or software); anything that fails is discarded and the built-in template is used.
- **Email report**: set `EMAIL_ENABLED=true` and the SMTP fields in `.env` (for Gmail, an App Password).
  Email stays off until every field is set.

## 11. Security and privacy

- Secrets live only in `.env` (gitignored): API key, SMTP password, Telegram token. No Indeed password anywhere.
- Personal data (contact details, database, documents, screenshots, logs, browser profile) is under `data\`
  and gitignored config files, readable only by her Windows account after install.
- The dashboard listens on 127.0.0.1 only and refuses other computers.
- Logs redact email addresses and phone numbers. The database is backed up before every run (last 21 kept,
  `data\backups`).
- Job listings are treated as untrusted: sentences that try to instruct an AI or ask for secrets are removed
  before analysis, the job is flagged, and it is never auto-submitted.

## 12. Troubleshooting

| Symptom | Fix |
|---|---|
| Report says *paused: login* | Run the sign-in shortcut and sign in again. |
| Report says *paused: captcha* | Indeed wants a human check. Run the sign-in shortcut, browse Indeed for a minute, complete the check yourself. If it keeps happening, lower `max_searches_per_run` in Settings. |
| `doctor --live` finds 0 search cards | Indeed changed its page layout. Update `jobbot/indeed/selectors.py`. |
| Task did not run | Task Scheduler > AnaghaJobBot Run > History; `data\logs\scheduled.log`. PC must be on and signed in. |
| Wrong contact details on the CV | Edit `config\candidate_private.yaml`. |
| Want Sharjah / Ajman / Abu Dhabi again | Settings > Search locations, one per line. |

## 13. Limitations to know

- **Indeed's terms of service restrict automated use of the site.** The bot works through her own signed-in
  account, at a slow pace (6 seconds between pages, at most 60 vacancy pages a day), with no stealth tricks and
  stopping at every security check. Even so, Indeed may show more verification or restrict the account; that
  risk stays with the account owner. If that happens, stop the scheduled task and use the dashboard, reports
  and `import-jobs` (for example with listings found through Claude's Indeed connector) and apply by hand.
- Indeed Apply forms differ by employer. Unusual question types stop the run for that job rather than guessing.
- Applications on employers' own websites are not filled automatically.
