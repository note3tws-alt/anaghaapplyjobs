"""Real browser (Chromium) against the offline mock Indeed site."""
import tempfile
from pathlib import Path

import pytest

from jobbot.config import load_profile
from jobbot.indeed.apply import run_apply
from jobbot.indeed.browser import BrowserSession, PauseRequired
from jobbot.indeed.search import read_job, search
from jobbot.mock_indeed import MockIndeed
from jobbot.screening import Answerer


@pytest.fixture
def env(settings, tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4 test")
    with MockIndeed() as m:
        settings["browser"]["base_url"] = m.base_url
        with BrowserSession(settings, headless=True, pace_seconds=0, profile_dir=tmp_path / "profile") as b:
            yield m, b, str(cv)


def _job(b, cards, title):
    c = next(c for c in cards if c["title"].startswith(title))
    return {**c, **read_job(b, c["url"]), "id": 1}


def test_search_and_read(env):
    m, b, _ = env
    cards = search(b, "Medical Coder", "Dubai", 7)
    titles = {c["title"] for c in cards}
    assert "Junior Medical Coder (CPC Freshers Welcome)" in titles
    assert all("Sharjah" not in c["location"] for c in cards)
    j = _job(b, cards, "Junior Medical Coder")
    assert j["company"] == "Demo Polyclinic LLC" and "ICD-10-CM" in j["description"] and j["apply_type"] == "indeed_apply"


def test_review_mode_never_submits(env):
    m, b, cv = env
    j = _job(b, search(b, "Medical Coder", "Dubai", 7), "Junior Medical Coder")
    r = run_apply(b, j, cv, Answerer(load_profile()), submit=False)
    assert r.status == "ready_for_review" and r.cv_uploaded and not r.pending
    assert m.submissions == []
    assert Path(r.screenshot).exists()


def test_submit_confirms(env):
    m, b, cv = env
    j = _job(b, search(b, "Medical Coder", "Dubai", 7), "Junior Medical Coder")
    r = run_apply(b, j, cv, Answerer(load_profile()), submit=True)
    assert r.status == "submitted" and "submitted" in r.confirmation.lower()
    assert m.submissions == ["fx-junior-coder"] and m.uploads["fx-junior-coder"].endswith(".pdf")


def test_unverified_work_authorisation_stops_even_when_submitting(env):
    m, b, cv = env
    j = _job(b, search(b, "Submission", "Dubai", 7), "Submission & Resubmission")
    r = run_apply(b, j, cv, Answerer(load_profile()), submit=True)
    assert r.status == "needs_attention" and m.submissions == []
    assert "authorized to work" in r.pending[0]["question"]


def test_salary_question_stops(env):
    m, b, cv = env
    j = _job(b, search(b, "Insurance Coordinator", "Dubai", 7), "Medical Insurance Coordinator")
    r = run_apply(b, j, cv, Answerer(load_profile()), submit=True)
    assert r.status == "needs_attention" and "salary" in r.pending[0]["reason"] and m.submissions == []


def test_external_apply_is_left_to_her(env):
    m, b, cv = env
    j = _job(b, search(b, "Medical Coder", "Dubai", 7), "IP Medical Coder")
    assert run_apply(b, j, cv, Answerer(load_profile()), submit=True).status == "external_apply"


def test_captcha_pauses(env):
    m, b, _ = env
    m.captcha = True
    with pytest.raises(PauseRequired) as e:
        search(b, "Medical Coder", "Dubai", 7)
    assert e.value.kind == "captcha"
