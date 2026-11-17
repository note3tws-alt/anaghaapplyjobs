from fastapi.testclient import TestClient

from jobbot.dashboard.app import create_app
from jobbot.pipeline import run


def test_dashboard_api(settings, sample_jobs):
    run(settings, jobs=sample_jobs, use_ai=False, notify_enabled=False)
    c = TestClient(create_app())
    ov = c.get("/api/overview").json()
    assert ov["counts"]["jobs_discovered"] == len(sample_jobs) and ov["mode"] == "review" and not ov["auto_submit"]
    jobs = c.get("/api/jobs?min_score=50").json()
    assert jobs and jobs[0]["score"] >= jobs[-1]["score"]
    jid = jobs[0]["id"]
    d = c.get(f"/api/jobs/{jid}").json()
    assert d["score_breakdown"]["location"]["max"] == 10 and d["events"]
    assert c.get(f"/api/jobs/{jid}/file/cv").status_code == 200
    assert c.post(f"/api/jobs/{jid}/status", json={"status": "approved"}).json()["status"] == "approved"
    assert c.post(f"/api/jobs/{jid}/status", json={"status": "discovered"}).status_code == 400
    r = c.get("/api/reports").json()
    assert r["daily"] and c.get(f"/api/reports/daily/{r['daily'][0]}").status_code == 200
    assert c.get("/api/reports/daily/..%2f..%2fsecret").status_code in (400, 404)
    s = c.get("/api/settings").json()["settings"]
    s["daily_application_limit"] = 6
    assert c.put("/api/settings", json=s).json()["settings"]["daily_application_limit"] == 6
    s["application_mode"] = "auto"
    assert c.put("/api/settings", json=s).status_code == 400   # needs authorise first
    s["application_mode"] = "review"; s["match_threshold"] = 500
    assert c.put("/api/settings", json=s).status_code == 400
    assert "Job Assistant" in c.get("/").text
