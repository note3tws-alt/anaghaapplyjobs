from datetime import datetime
from pathlib import Path

from jobbot.config import auto_submit_allowed, load_settings, paths, rules_fingerprint, save_settings
from jobbot.db import DB, DUBAI
from jobbot.indeed.browser import BrowserSession
from jobbot.mock_indeed import MockIndeed
from jobbot.pipeline import is_scheduled_day, run


def _run(settings, mock, tmp_path):
    settings["browser"]["base_url"] = mock.base_url
    settings["max_searches_per_run"] = 8
    return run(settings, session_factory=lambda: BrowserSession(settings, headless=True, pace_seconds=0,
                                                                  profile_dir=tmp_path / "profile"),
               use_ai=False, notify_enabled=False)


def test_full_review_mode_run(settings, tmp_path):
    with MockIndeed() as m:
        stats = _run(settings, m, tmp_path)
        assert m.submissions == []                      # review mode: nothing submitted
    assert stats.paused is None and not [e for e in stats.errors if "failed" in e.lower()]
    assert stats.new_jobs >= 6 and stats.relevant >= 4
    assert stats.ready_for_review >= 2 and stats.needs_attention >= 1
    db = DB()
    review = db.list_jobs(status="ready_for_review")
    assert all(Path(j["cv_path"]).exists() and j["cv_version"] for j in review)
    assert db.list_jobs(status="rejected")
    report = Path(db.list_runs(1)[0]["report_path"])
    text = report.read_text()
    for section in ("Applications submitted today", "Waiting for Anagha's review", "Rejected vacancies and reasons",
                    "Technical errors"):
        assert section in text
    assert report.with_suffix(".html").exists()


def test_second_run_has_no_duplicates_and_submits_only_approved(settings, tmp_path):
    with MockIndeed() as m:
        _run(settings, m, tmp_path)
        db = DB()
        n = len(db.list_jobs(limit=1000))
        job = db.list_jobs(status="ready_for_review")[0]
        db.set_status(job["id"], "approved", "approved by Anagha in test")
        stats = _run(settings, m, tmp_path)
        assert stats.new_jobs == 0 and len(db.list_jobs(limit=1000)) == n
        assert len(m.submissions) == 1                  # only the job she approved
        j = db.get_job(job["id"])
        assert j["status"] == "submitted" and j["submission_confirmation"]


def test_login_required_pauses(settings, tmp_path):
    with MockIndeed(signed_in=False) as m:
        stats = _run(settings, m, tmp_path)
    assert stats.paused and stats.paused.startswith("login")
    assert DB().list_runs(1)[0]["status"] == "paused"


def test_auto_mode_needs_matching_authorisation(settings):
    s = load_settings()
    s["application_mode"] = "auto"
    assert not auto_submit_allowed(s)[0]
    s["authorisation"] = {"authorised": True, "rules_fingerprint": rules_fingerprint(s)}
    assert auto_submit_allowed(s)[0]
    s["match_threshold"] = 55                             # rules changed after authorising
    assert not auto_submit_allowed(s)[0]


def test_schedule_skips_sunday(settings):
    assert not is_scheduled_day(settings, datetime(2026, 11, 22, 9, 0, tzinfo=DUBAI))  # Sunday
    assert is_scheduled_day(settings, datetime(2026, 11, 21, 9, 0, tzinfo=DUBAI))      # Saturday
    assert settings["schedule"]["time"] == "09:00" and settings["locations"] == ["Dubai"]


def test_import_jobs_without_browser(settings, sample_jobs):
    stats = run(settings, jobs=sample_jobs, use_ai=False, notify_enabled=False)
    assert stats.new_jobs == len(sample_jobs) and stats.prepared >= 3


def test_location_titles_limits_searches():
    from jobbot.pipeline import search_plan
    s = {"job_titles": {"medical_coding": ["Medical Coder", "Junior Medical Coder"]},
         "locations": ["Dubai", "Sharjah"], "location_titles": {"Sharjah": ["Medical Coder"]},
         "max_searches_per_run": 50}
    assert [(t, l) for _, t, l in search_plan(s)] == [
        ("Medical Coder", "Dubai"), ("Medical Coder", "Sharjah"), ("Junior Medical Coder", "Dubai")]
