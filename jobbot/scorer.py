"""Suitability score (0-100) for Anagha, following the weights she asked for.

Medical coding relevance 25 | CPC relevance 20 | Experience 20 | Skills 15 | Education 10 | Location 10
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from jobbot.extractor import CANDIDATE_SKILLS, Requirements

LOCATION_POINTS = {"dubai": 10, "sharjah": 8, "ajman": 8, "abu dhabi": 6}


@dataclass
class Score:
    total: int
    classification: str
    breakdown: dict
    reasons: list[str] = field(default_factory=list)
    reject_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def classify(total: int) -> str:
    if total >= 80:
        return "Excellent match"
    if total >= 65:
        return "Good match"
    if total >= 50:
        return "Possible match"
    return "Reject"


def _coding_relevance(r: Requirements) -> tuple[int, str]:
    title = r.title.lower()
    if re.search(r"medical cod|\bcoder\b|\bcoding\b", title):
        pts = 25 if not re.search(r"receptionist|marketing|sales", title) else 12
        return pts, "Medical coding role"
    if r.category == "billing_rcm":
        pts = 20 if {"ICD-10-CM", "CPT"} & set(r.skills) else 17
        return pts, "Billing / RCM role that uses coding knowledge"
    if r.category == "medical_insurance":
        pts = 18 if {"ICD-10-CM", "CPT", "Pre-authorization", "Claims submission"} & set(r.skills) else 14
        return pts, "Medical insurance role matching her RCM work"
    if {"ICD-10-CM", "CPT", "HCPCS"} & set(r.skills):
        return 10, "Mentions coding but the role is not a coding job"
    return 0, "Not a medical coding, insurance or billing role"


def _cpc_relevance(r: Requirements) -> tuple[int, str]:
    certs = set(r.certifications_required)
    if "CPC" in certs or "AAPC (any)" in certs:
        return 20, "Asks for CPC / AAPC certification, which she holds"
    if certs & {"CCS", "CCA", "AHIMA (any)", "COC", "CIC", "CCS-P"}:
        if r.certification_mandatory:
            return 8, "Asks for a different coding certificate (not CPC)"
        return 12, "Prefers another coding certificate; CPC usually accepted"
    if r.category == "medical_coding":
        return 15, "Coding role; CPC is a strong advantage"
    if r.category in ("billing_rcm", "medical_insurance"):
        return 10, "CPC is a plus for this role"
    return 4, "CPC not relevant"


def _experience(r: Requirements, candidate_years: float) -> tuple[int, str]:
    lo = r.min_years
    if r.senior_title and (lo is None or lo >= 2):
        base = 4
        why = "Senior-level title"
    elif lo is None:
        base, why = 16, "No experience requirement stated"
    elif lo <= candidate_years + 0.25:
        base, why = 20, "Experience requirement met"
    elif lo <= 1:
        # She asked not to reject good jobs that only prefer one year.
        base, why = 15, "Asks for about 1 year; still worth applying"
    elif lo <= 2:
        base, why = 10, f"Asks for {r.experience_text or '1-2 years'}"
    elif lo <= 3:
        base, why = 5, "Asks for about 3 years"
    else:
        base, why = 2, f"Asks for {lo:g}+ years"
    if r.entry_level_friendly:
        base = min(20, base + 5)
        why += "; open to entry-level / freshers"
    return base, why


def _skills(r: Requirements) -> tuple[int, str, list[str], list[str]]:
    wanted = [s for s in r.skills if s not in ("Insurance / TPA",)]
    if not wanted:
        return 10, "No specific technical skills listed", [], []
    have = [s for s in wanted if s in CANDIDATE_SKILLS]
    missing = [s for s in wanted if s not in CANDIDATE_SKILLS]
    pts = round(15 * len(have) / len(wanted))
    return pts, f"Has {len(have)} of {len(wanted)} skills mentioned", have, missing


def _education(r: Requirements) -> tuple[int, str]:
    ed = set(r.education)
    if "nursing_pharmacy" in ed and not ({"any_degree", "life_science"} & ed):
        return 5, "Asks for a nursing / pharmacy type degree"
    if "allied_health" in ed and "life_science" not in ed:
        return 8, "Prefers allied health; her MSc Zoology is a related life science"
    return 10, "MSc / BSc Zoology meets the education requirement"


def _location(r: Requirements, allowed: list[str], strict: bool) -> tuple[int, str, str | None]:
    loc = (r.location or "").lower()
    allowed_l = [a.lower() for a in allowed]
    in_allowed = any(a in loc for a in allowed_l)
    if strict and loc and not in_allowed:
        return 0, f"{r.location} is outside the chosen locations", f"Location outside {', '.join(allowed)}"
    for place, pts in LOCATION_POINTS.items():
        if place in loc:
            return pts, f"Located in {place.title()}", None
    if "remote" in loc:
        return 9, "Remote", None
    if re.search(r"uae|united arab emirates|al ain|ras al khaimah|fujairah|umm al", loc):
        return 5, "Elsewhere in the UAE", None
    if not loc:
        return 5, "Location not stated", None
    return 0, "Outside the UAE", "Outside the UAE"


def _words(s: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip() + " "


def excluded_company(company: str, excluded: list[str]) -> str | None:
    """Return the matching entry if the employer is on the do-not-apply list (whole-word, case-insensitive)."""
    name = _words(company)
    for e in excluded:
        if e and _words(e).strip() and _words(e) in name:
            return e
    return None


def score(r: Requirements, *, candidate_years: float, allowed_locations: list[str],
          strict_locations: bool = True, minimum_salary_aed: int = 0,
          excluded_companies: list[str] | None = None) -> Score:
    c, c_why = _coding_relevance(r)
    p, p_why = _cpc_relevance(r)
    e, e_why = _experience(r, candidate_years)
    s, s_why, have, missing = _skills(r)
    ed, ed_why = _education(r)
    loc, loc_why, loc_reject = _location(r, allowed_locations, strict_locations)

    total = c + p + e + s + ed + loc
    adjustments = []
    if r.entry_level_friendly and r.certifications_required and ("CPC" in r.certifications_required
                                                                   or "AAPC (any)" in r.certifications_required):
        total += 5
        adjustments.append("+5 entry-level employer that asks for CPC")
    if any("non-coding role" in f for f in r.flags):
        total -= 10
        adjustments.append("-10 mixed non-coding role")
    if any("Inpatient / DRG" in f for f in r.flags):
        total -= 8
        adjustments.append("-8 inpatient / DRG focus")
    if any("Arabic" in f for f in r.flags):
        total -= 10
        adjustments.append("-10 requires Arabic")
    total = max(0, min(100, total))

    reject = None
    blocked = excluded_company(r.company, excluded_companies or [])
    if blocked:
        reject = f"Excluded employer ({blocked})"
    elif loc_reject:
        reject = loc_reject
    elif c == 0:
        reject = "Not a medical coding, insurance or billing role"
    elif minimum_salary_aed and r.salary_max_aed and r.salary_max_aed < minimum_salary_aed:
        reject = f"Salary below AED {minimum_salary_aed:,}"
    elif r.min_years is not None and r.min_years >= 4:
        reject = f"Needs {r.min_years:g}+ years of experience"

    cls = "Reject" if reject else classify(total)
    if not reject and cls == "Reject":
        reject = "Score below 50"

    breakdown = {
        "medical_coding_relevance": {"points": c, "max": 25, "why": c_why},
        "cpc_relevance": {"points": p, "max": 20, "why": p_why},
        "experience": {"points": e, "max": 20, "why": e_why},
        "technical_skills": {"points": s, "max": 15, "why": s_why, "matched": have, "missing": missing},
        "education": {"points": ed, "max": 10, "why": ed_why},
        "location": {"points": loc, "max": 10, "why": loc_why},
        "adjustments": adjustments,
    }
    reasons = [c_why, p_why, e_why, s_why, loc_why, *adjustments]
    return Score(total=total, classification=cls, breakdown=breakdown, reasons=reasons, reject_reason=reject)


def candidate_years_from_profile(profile: dict, today=None) -> float:
    """Paid experience in years from experience_start (YYYY-MM). Internship is not counted."""
    from datetime import date
    start = str(profile.get("experience_start") or "")
    m = re.match(r"(\d{4})-(\d{1,2})", start)
    if not m:
        return 0.0
    today = today or date.today()
    months = (today.year - int(m.group(1))) * 12 + today.month - int(m.group(2))
    return max(0.0, round(months / 12, 2))
