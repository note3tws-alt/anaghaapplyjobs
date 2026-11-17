from jobbot.db import DB


def test_duplicates_by_key_url_and_company_title():
    db = DB()
    a, new = db.upsert_job({"job_key": "indeed-1", "url": "u1", "company": "Demo Clinic LLC", "title": "Medical Coder - Dubai"})
    assert new
    assert db.upsert_job({"job_key": "indeed-1", "url": "u1"}) == (a, False)
    assert db.find_duplicate(url="u1")["id"] == a
    assert db.find_duplicate(company="demo clinic", title="Medical Coder")["id"] == a
    db.set_status(a, "submitted", "test", application_date="2026-11-16T09:10:00+04:00")
    assert db.already_applied("Demo Clinic", "Medical Coder (Urgent)")["id"] == a
    assert db.count_submitted_on("2026-11-16") == 1


def test_history_and_backup():
    db = DB()
    a, _ = db.upsert_job({"job_key": "k", "company": "C", "title": "T"})
    db.set_status(a, "shortlisted", "score 80")
    events = [e["event"] for e in db.events_for(a)]
    assert events == ["discovered", "status:shortlisted"]
    b = db.backup()
    assert b.exists() and b.stat().st_size > 0


def test_unknown_status_refused():
    import pytest
    db = DB()
    a, _ = db.upsert_job({"job_key": "k2"})
    with pytest.raises(ValueError):
        db.set_status(a, "hacked")
