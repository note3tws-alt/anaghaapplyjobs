"""Turn a vacancy's text into structured requirements. Rule based, so it is fast, free and testable."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

WORD_NUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10}

CERTS = {
    "CPC": r"\bcpc\b|certified professional coder",
    "AAPC (any)": r"\baapc\b",
    "CCS": r"\bccs\b(?!-p)|certified coding specialist(?! ?- ?physician)",
    "CCS-P": r"\bccs-p\b",
    "CCA": r"\bcca\b|certified coding associate",
    "CIC": r"\bcic\b|certified inpatient coder",
    "COC": r"\bcoc\b|certified outpatient coder",
    "CRC": r"\bcrc\b|certified risk adjustment",
    "CPB": r"\bcpb\b|certified professional biller",
    "AHIMA (any)": r"\bahima\b",
    "DHA/DOH/MOH licence": r"\b(?:dha|doh|haad|moh|mohap)\b[^.\n]{0,40}\b(?:licen[cs]e|eligib|pass|exam)",
}

# Skills we look for in a vacancy. Keys are display names; values are regexes.
SKILLS = {
    "ICD-10-CM": r"icd[- ]?10(?:[- ]?cm)?|icd[- ]?9",
    "CPT": r"\bcpt\b",
    "HCPCS": r"\bhcpcs\b",
    "E/M coding": r"\be ?(?:/|&|and) ?m\b|evaluation (?:and|&) management",
    "Modifiers": r"\bmodifiers?\b",
    "DRG": r"\b(?:ir-|ap-|ms-)?drgs?\b",
    "Medical terminology": r"medical terminology",
    "Anatomy & physiology": r"anatomy|physiology",
    "Record abstraction": r"abstract(?:ion|ing|s)?\b",
    "Clinical documentation review": r"clinical documentation|documentation (?:review|consistency|deficienc)",
    "Physician queries": r"physician quer|query (?:physicians|doctors)",
    "Pre-authorization": r"pre[- ]?auth(?:ori[sz]ation)?s?|prior auth|pre[- ]?approval|insurance approvals?",
    "Claims submission": r"claims? (?:submission|preparation|processing|upload)|submit(?:ting)? claims|resubmission",
    "Denial management": r"denial|rejections?|resubmission|re-submission",
    "eClaimLink": r"e[- ]?claim ?link",
    "Shafafiya": r"shafafiya",
    "Mediware": r"mediware",
    "Payer follow-up": r"follow[- ]?ups? with (?:insurance|payers?|tpa)|payer follow|insurance follow",
    "RCM": r"\brcm\b|revenue cycle",
    "Medical billing": r"medical billing|\bbilling\b",
    "MS Office / Excel": r"ms office|microsoft office|\bexcel\b",
    "Insurance / TPA": r"\btpa\b|insurance compan|payers?\b",
    "Inpatient coding": r"\binpatient\b|\bip coding\b|\bip coder\b",
    "Outpatient coding": r"\boutpatient\b|\bop coding\b|\bop coder\b|\bo/p\b",
    "HIS / EMR software": r"\b(?:his|emr|ehr)\b|cerner|epic|trakcare|oracle health",
}

# Skills that her CV supports (subset of the keys above).
CANDIDATE_SKILLS = {
    "ICD-10-CM", "CPT", "HCPCS", "E/M coding", "Modifiers", "Medical terminology", "Anatomy & physiology",
    "Record abstraction", "Clinical documentation review", "Pre-authorization", "Claims submission",
    "eClaimLink", "Mediware", "Payer follow-up", "RCM", "MS Office / Excel", "Insurance / TPA",
    "Outpatient coding", "HIS / EMR software",
}

EDUCATION = {
    "any_degree": r"bachelor'?s?|graduate|degree|\bbsc\b|\bb\.sc\b|\bmsc\b",
    "life_science": r"life science|biolog|zoolog|science background|medical background|para ?medical",
    "allied_health": r"allied health|health information|him\b",
    "nursing_pharmacy": r"\bnursing\b|\bpharmacy\b|\bbds\b|\bmbbs\b|\bbams\b|\bbhms\b|physiotherap",
    "diploma": r"diploma|high school|secondary school",
}

SENIOR_TITLE = r"\b(senior|sr\.?|lead|head|manager|supervisor|team leader|auditor|specialist ii|principal)\b"
ENTRY_TERMS = r"\bfreshers?\b|entry[- ]level|\btrainee\b|\bjunior\b|no experience (?:required|needed)|0\s*[-–to]+\s*1 years?|recently certified|newly certified|certified freshers?|graduates? (?:are )?welcome"

UAE_LOCATIONS = ["dubai", "sharjah", "ajman", "abu dhabi", "al ain", "ras al khaimah", "fujairah",
                 "umm al quwain", "uae", "united arab emirates"]

SALARY_RE = re.compile(
    r"(?:aed|dhs?|dirhams?)\s*\.?\s*([\d,]{3,7})(?:\s*(?:-|–|to)\s*(?:aed|dhs?)?\s*([\d,]{3,7}))?"
    r"|([\d,]{3,7})(?:\s*(?:-|–|to)\s*([\d,]{3,7}))?\s*(?:aed|dhs?|dirhams?)", re.I)


@dataclass
class Requirements:
    title: str = ""
    company: str = ""
    location: str = ""
    salary_text: str = ""
    salary_min_aed: int | None = None
    salary_max_aed: int | None = None
    salary_period: str | None = None
    min_years: float | None = None
    max_years: float | None = None
    experience_text: str = ""
    entry_level_friendly: bool = False
    education: list[str] = field(default_factory=list)
    certifications_required: list[str] = field(default_factory=list)
    certification_mandatory: bool = False
    skills: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    category: str = "other"
    senior_title: bool = False
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _num(tok: str) -> float | None:
    tok = tok.strip().lower()
    if tok in WORD_NUM:
        return float(WORD_NUM[tok])
    try:
        return float(tok)
    except ValueError:
        return None


def extract_years(text: str) -> tuple[float | None, float | None, str]:
    t = text.lower()
    # "minimum of one-two (1-2) years", "1-2 years", "2 to 3 years", "at least two (2) years", "2+ years"
    patterns = [
        r"(\d+(?:\.\d+)?)\s*\)?\s*(?:-|–|to)\s*\(?(\d+(?:\.\d+)?)\s*\)?\s*(?:\+\s*)?years?",
        r"(\d+(?:\.\d+)?)\s*\+?\s*\)?\s*years?",
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b\s*(?:\(\d+\))?\s*(?:\+\s*)?years?",
    ]
    best: tuple[float | None, float | None, str] = (None, None, "")
    for line in re.split(r"[\n.;]", t):
        if not re.search(r"experience|exp\b|years? (?:of|in)", line):
            continue
        for i, pat in enumerate(patterns):
            m = re.search(pat, line)
            if not m:
                continue
            if i == 0:
                lo, hi = _num(m.group(1)), _num(m.group(2))
            else:
                lo, hi = _num(m.group(1)), None
            if lo is None or lo > 30:
                continue
            if best[0] is None or lo > best[0]:
                ms = max(0, m.start() - 40)
                best = (lo, hi, (("…" if ms else "") + line[ms:m.end() + 40]).strip(" -•*")[:120])
            break
    return best


def extract_salary(text: str) -> tuple[str, int | None, int | None, str | None]:
    m = SALARY_RE.search(text or "")
    if not m:
        return "", None, None, None
    nums = [g for g in m.groups() if g]
    vals = [int(n.replace(",", "")) for n in nums if n.replace(",", "").isdigit()]
    if not vals:
        return "", None, None, None
    window = text[max(0, m.start() - 20): m.end() + 30].lower()
    period = "year" if re.search(r"year|annum|annual|p\.?a\b", window) else "month"
    lo, hi = vals[0], (vals[1] if len(vals) > 1 else None)
    if period == "year":
        lo = lo // 12
        hi = hi // 12 if hi else None
    return m.group(0).strip(), lo, hi, period


def classify_category(title: str, text: str) -> str:
    t = f"{title} {text[:600]}".lower()
    tl = title.lower()
    if re.search(r"cod(?:er|ing)", tl):
        return "medical_coding"
    if re.search(r"billing|rcm|revenue cycle", tl):
        return "billing_rcm"
    if re.search(r"insurance|pre[- ]?auth|approval|claims?|submission|tpa|denial", tl):
        return "medical_insurance"
    if re.search(r"medical cod|icd-?10|\bcpt\b", t):
        return "medical_coding"
    if re.search(r"billing|revenue cycle|\brcm\b", t):
        return "billing_rcm"
    if re.search(r"insurance|pre[- ]?auth|claims?", t):
        return "medical_insurance"
    return "other"


def extract_responsibilities(text: str, limit: int = 8) -> list[str]:
    out = []
    verbs = r"^(?:-|•|\*|\d+[.)])?\s*(?:the incumbent )?(ensure|review|assign|code|abstract|evaluate|analy[sz]e|prepare|submit|upload|verify|coordinate|follow|identify|maintain|perform|provide|check|process|communicate|liaise|handle|obtain|monitor|track|adhere|query|assist|manage|resolve)"
    for line in text.splitlines():
        s = line.strip(" -•*\t")
        if 25 <= len(s) <= 260 and re.search(verbs, line.strip().lower()):
            if s not in out:
                out.append(s)
        if len(out) >= limit:
            break
    return out


def extract(title: str, company: str, location: str, description: str, salary_text: str = "") -> Requirements:
    text = description or ""
    low = text.lower()
    r = Requirements(title=title or "", company=company or "", location=location or "")

    s_text, s_lo, s_hi, s_per = extract_salary(salary_text or "") if salary_text else ("", None, None, None)
    if not s_text:
        s_text, s_lo, s_hi, s_per = extract_salary(text)
    r.salary_text = salary_text or s_text
    r.salary_min_aed, r.salary_max_aed, r.salary_period = s_lo, s_hi, s_per

    r.min_years, r.max_years, r.experience_text = extract_years(text)
    r.entry_level_friendly = bool(re.search(ENTRY_TERMS, f"{title}\n{low}", re.I))
    r.education = [k for k, pat in EDUCATION.items() if re.search(pat, low)]
    r.certifications_required = [k for k, pat in CERTS.items() if re.search(pat, low)]
    r.certification_mandatory = bool(re.search(
        r"(?:certif\w*|cpc|ccs|aapc|ahima)[^.\n]{0,60}\b(?:mandatory|must|required|essential)\b"
        r"|\b(?:mandatory|must have|required|essential)\b[^.\n]{0,60}(?:certif|cpc|ccs|aapc|ahima)", low))
    r.skills = [k for k, pat in SKILLS.items() if re.search(pat, low)]
    r.responsibilities = extract_responsibilities(text)
    r.category = classify_category(title or "", text)
    r.senior_title = bool(re.search(SENIOR_TITLE, (title or "").lower()))

    flags = []
    if re.search(r"\b(female|male) (?:only|candidates? only|preferred)\b|\bfemale\b.*\b(?:receptionist|staff)\b", f"{title} {low}"):
        flags.append("States a gender requirement; check before applying")
    if "DHA/DOH/MOH licence" in r.certifications_required:
        flags.append("Mentions a DHA/DOH/MOH licence or exam, which is not on the CV")
    if re.search(r"arabic (?:speaking|is a must|mandatory|required)|must speak arabic|fluent in arabic", low):
        flags.append("Requires Arabic, which is not on the CV")
    if re.search(r"receptionist|marketing|sales|nurse\b|driver", (title or "").lower()):
        flags.append("Title mixes in a non-coding role")
    if re.search(r"\bdrg\b", low) and re.search(r"\binpatient\b|\bip\b", f"{title} {low}".lower()):
        flags.append("Inpatient / DRG coding focus; her training is ICD-10-CM, CPT, HCPCS")
    if r.min_years is not None and r.min_years >= 2:
        flags.append(f"Asks for {r.experience_text or str(r.min_years) + ' years'}")
    r.flags = flags
    return r
