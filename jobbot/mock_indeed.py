"""A small offline imitation of Indeed's pages, for tests and `python -m jobbot demo`.

It mimics the structure the bot relies on (search cards, vacancy page, Indeed Apply steps, review and
confirmation pages, CAPTCHA and sign-in pages). It is NOT Indeed and never contacts Indeed.
"""
from __future__ import annotations

import html
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURE_JOBS = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "jobs" / "sample_jobs.json"

# Extra questions per job key; the default flow asks verified questions only.
EXTRA_QUESTIONS = {
    "fixture-insurance-coord": [("text", "What is your expected monthly salary (AED)?", None)],
    "indeed-fixture-submission-officer": [("radio", "Are you legally authorized to work in the UAE?", ["Yes", "No"])],
}
EXTERNAL = {"indeed-fixture-ip-coder"}


def _page(title: str, body: str, signed_in: bool = True) -> bytes:
    header = ('<a data-gnav-element-name="AccountMenu" href="/account/view">Account</a>' if signed_in
              else '<a data-gnav-element-name="SignIn" href="/account/login">Sign in</a>')
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title></head>"
            f"<body><header>{header}</header><main>{body}</main></body></html>").encode()


class MockIndeed:
    def __init__(self, jobs_file: Path = FIXTURE_JOBS, signed_in: bool = True):
        self.jobs = {j["job_key"].replace("indeed-", "").replace("fixture-", "fx-"): j
                     for j in json.loads(Path(jobs_file).read_text(encoding="utf-8"))}
        self.signed_in = signed_in
        self.captcha = False
        self.submissions: list[str] = []
        self.uploads: dict[str, str] = {}
        self.server: ThreadingHTTPServer | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "MockIndeed":
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # keep test output quiet
                pass

            def _send(self, body: bytes, code: int = 200):
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                u = urlparse(self.path)
                parts = u.path.strip("/").split("/")
                if len(parts) == 3 and parts[0] == "apply":
                    jk, step = parts[1], parts[2]
                    if step == "1" and b"filename=" in raw:
                        mock.uploads[jk] = raw.split(b'filename="')[1].split(b'"')[0].decode()
                    if step == "submit":
                        mock.submissions.append(jk)
                        return self._send(_page("Application submitted",
                                                "<h1>Your application has been submitted</h1><p>You will get an email confirmation from Indeed.</p>"))
                    self.send_response(303)
                    self.send_header("Location", f"/apply/{jk}/{int(step) + 1}")
                    self.end_headers()
                    return
                self._send(b"not found", 404)

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                if mock.captcha:
                    return self._send(_page("Just a moment...",
                                            "<p>Additional Verification Required</p><iframe src='https://hcaptcha.com/x'></iframe>"))
                if u.path == "/":
                    return self._send(_page("Indeed UAE", "<h1>Find jobs</h1>", mock.signed_in))
                if u.path.startswith("/account/login"):
                    return self._send(_page("Sign in", "<form><input type=email></form>", False))
                if u.path == "/jobs":
                    term = q.get("q", "").lower()
                    loc = q.get("l", "").lower()
                    cards = []
                    for jk, j in mock.jobs.items():
                        words = [w for w in term.split() if w not in ("medical",)]
                        hay = (j["title"] + " " + j["description"]).lower()
                        if loc and loc not in j["location"].lower():
                            continue
                        if words and not any(w in hay for w in words):
                            continue
                        sal = f"<div data-testid='attribute_snippet_testid'>{html.escape(j['salary'])}</div>" if j["salary"] else ""
                        cards.append(
                            f"<li><div class='job_seen_beacon'><h2 class='jobTitle'><a class='jcs-JobTitle' data-jk='{jk}' "
                            f"href='/viewjob?jk={jk}'><span title='{html.escape(j['title'])}'>{html.escape(j['title'])}</span></a></h2>"
                            f"<span data-testid='company-name'>{html.escape(j['company'])}</span>"
                            f"<div data-testid='text-location'>{html.escape(j['location'])}</div>{sal}"
                            f"{'' if j['job_key'] in EXTERNAL else '<span data-testid=indeedApply>Easily apply</span>'}"
                            f"</div></li>")
                    return self._send(_page("Jobs", f"<ul>{''.join(cards)}</ul>", mock.signed_in))
                if u.path == "/viewjob":
                    jk = q.get("jk", "")
                    j = mock.jobs.get(jk)
                    if not j:
                        return self._send(b"gone", 404)
                    desc = html.escape(j["description"]).replace("\n", "<br>")
                    key = j["job_key"]
                    if key in EXTERNAL:
                        btn = "<div id='applyButtonLinkContainer'><a href='https://employer.example.invalid/careers'>Apply on company site</a></div>"
                    else:
                        btn = f"<button id='indeedApplyButton' onclick=\"window.open('/apply/{jk}/1','_blank')\">Apply now</button>"
                    sal = f"<div id='salaryInfoAndJobType'>{html.escape(j['salary'])}</div>" if j["salary"] else ""
                    return self._send(_page(j["title"],
                        f"<h1 data-testid='jobsearch-JobInfoHeader-title'>{html.escape(j['title'])}</h1>"
                        f"<div data-testid='inlineHeader-companyName'>{html.escape(j['company'])}</div>"
                        f"<div data-testid='inlineHeader-companyLocation'>{html.escape(j['location'])}</div>{sal}"
                        f"{btn}<div id='jobDescriptionText'>{desc}</div>", mock.signed_in))
                if u.path.startswith("/apply/"):
                    _, jk, step = u.path.strip("/").split("/")
                    j = mock.jobs.get(jk)
                    if not j:
                        return self._send(b"gone", 404)
                    if step == "1":
                        body = (f"<h2>Add your contact information</h2><form method='post' enctype='multipart/form-data' action='/apply/{jk}/1'>"
                                "<label for='fn'>First name</label><input id='fn' name='fn' value='Anagha' required>"
                                "<label for='ln'>Last name</label><input id='ln' name='ln' value='P'>"
                                "<label for='em'>Email</label><input id='em' name='em' value='' required>"
                                "<label for='cv'>Upload a resume</label><input id='cv' type='file' name='cv'>"
                                "<button type='submit' data-testid='ia-continue-button'>Continue</button></form>")
                    elif step == "2":
                        qs = [("radio", "Do you have a valid CPC certification?", ["Yes", "No"]),
                              ("radio", "Are you currently living in Dubai?", ["Yes", "No"])]
                        qs += EXTRA_QUESTIONS.get(j["job_key"], [])
                        items = []
                        for i, (kind, label, opts) in enumerate(qs):
                            if kind == "radio":
                                radios = "".join(f"<input type='radio' id='q{i}{o}' name='q{i}' value='{o}' required><label for='q{i}{o}'>{o}</label>" for o in opts)
                                items.append(f"<fieldset data-testid='question-{i}'><legend>{html.escape(label)}</legend>{radios}</fieldset>")
                            else:
                                items.append(f"<div data-testid='question-{i}'><label for='q{i}'>{html.escape(label)}</label><input id='q{i}' name='q{i}' required></div>")
                        body = (f"<h2>Answer these questions from the employer</h2><form method='post' action='/apply/{jk}/2'>"
                                f"{''.join(items)}<button type='submit' data-testid='ia-continue-button'>Continue</button></form>")
                    elif step == "3":
                        body = (f"<h2>Please review your application</h2><p>{html.escape(j['title'])} at {html.escape(j['company'])}</p>"
                                f"<form method='post' action='/apply/{jk}/submit'><button type='submit' data-testid='submit-application-button'>Submit your application</button></form>")
                    else:
                        body = "<p>Unknown step</p>"
                    return self._send(_page("Apply", body, mock.signed_in))
                self._send(b"not found", 404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
