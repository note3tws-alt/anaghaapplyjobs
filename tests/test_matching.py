from jobbot.extractor import extract, extract_salary, extract_years
from jobbot.sanitize import injection_flags, strip_injections
from jobbot.scorer import candidate_years_from_profile, classify, score


def _score(j, allowed=("Dubai",)):
    r = extract(j["title"], j["company"], j["location"], strip_injections(j["description"])[0], j["salary"])
    return r, score(r, candidate_years=0.1, allowed_locations=list(allowed))


def by_key(jobs, key):
    return next(j for j in jobs if j["job_key"] == key)


def test_classification_bands():
    assert classify(80) == "Excellent match" and classify(65) == "Good match"
    assert classify(50) == "Possible match" and classify(49) == "Reject"


def test_entry_level_cpc_job_scores_top(sample_jobs):
    r, s = _score(by_key(sample_jobs, "fixture-junior-coder"))
    assert r.entry_level_friendly and "CPC" in r.certifications_required
    assert s.total >= 90 and s.classification == "Excellent match"
    assert r.salary_min_aed == 4000 and r.salary_max_aed == 5500


def test_one_to_two_years_is_not_rejected(sample_jobs):
    r, s = _score(by_key(sample_jobs, "indeed-fixture-coding-exec"))  # real Indeed UAE listing
    assert r.min_years == 1 and r.max_years == 2
    assert s.reject_reason is None and s.total >= 65


def test_insurance_role_matches_her_rcm_work(sample_jobs):
    r, s = _score(by_key(sample_jobs, "fixture-insurance-coord"))
    assert r.category == "medical_insurance"
    assert {"Pre-authorization", "eClaimLink"} <= set(r.skills)
    assert s.classification in ("Good match", "Excellent match")


def test_dubai_only_rejects_sharjah(sample_jobs):
    _, s = _score(by_key(sample_jobs, "fixture-sharjah"))
    assert s.classification == "Reject" and "Location" in s.reject_reason
    _, s2 = _score(by_key(sample_jobs, "fixture-sharjah"), allowed=("Dubai", "Sharjah"))
    assert s2.reject_reason is None


def test_senior_and_unrelated_rejected(sample_jobs):
    assert _score(by_key(sample_jobs, "fixture-senior"))[1].classification == "Reject"
    assert "Not a medical coding" in _score(by_key(sample_jobs, "fixture-unrelated"))[1].reject_reason


def test_injected_text_is_removed_and_flagged(sample_jobs):
    j = by_key(sample_jobs, "fixture-injection")
    assert injection_flags(j["description"])
    clean, removed = strip_injections(j["description"])
    assert "passport" not in clean and len(removed) == 2
    r, s = _score(j)
    assert r.min_years == 1  # the injected "5 years" claim did not leak into extraction


def test_year_and_salary_parsers():
    assert extract_years("at least two (2) years of coding experience")[0] == 2
    assert extract_years("Minimum of one-two (1-2) years coding experience")[:2] == (1, 2)
    assert extract_salary("AED 60,000 per year")[1] == 5000


def test_candidate_years_from_start_date():
    from datetime import date
    assert candidate_years_from_profile({"experience_start": "2026-10"}, date(2027, 10, 1)) == 1.0
