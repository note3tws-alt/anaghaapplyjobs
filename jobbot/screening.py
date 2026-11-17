"""Answer application screening questions only from verified answers. Everything else stops."""
from __future__ import annotations

import re
from dataclasses import dataclass

from jobbot.config import load_answers

# These always stop, whatever the answers file says.
ALWAYS_STOP = {
    "legal": r"declar|certify that|attest|criminal|convict|court|background check|legal(?:ly)? binding|penalt|under oath",
    "terms": r"\bagree\b|terms (?:and|&) conditions|consent|acknowledge|privacy (?:policy|notice)|non[- ]?compete|bond\b|deposit|fee\b|pay (?:for|a)",
    "salary": r"salary|expected pay|compensation|\bctc\b|remuneration|expected (?:monthly )?(?:pay|package)|current pay",
    "sensitive": r"passport|emirates id|\beid\b|date of birth|\bdob\b|\bage\b|marital|religio|bank|iban|national id|social security|photo(?:graph)?\b|medical (?:history|condition)|disabilit|pregnan|family members?|references? (?:name|contact)|otp|password",
}

# Contact fields Indeed may ask for; filled from the CV contact details only.
CONTACT_FIELDS = {
    "first_name": r"^first name|given name",
    "last_name": r"^last name|surname|family name",
    "full_name": r"^(?:full )?name\b",
    "email": r"e-?mail",
    "phone": r"phone|mobile|contact number",
    "city": r"^city|location|where do you live|current city",
}


@dataclass
class Answer:
    question: str
    answer: str | None
    ok: bool
    reason: str = ""
    rule: str | None = None


class Answerer:
    def __init__(self, profile: dict, answers: dict | None = None):
        self.profile = profile
        self.rules = (answers if answers is not None else load_answers()).get("answers", [])

    def contact_value(self, key: str) -> str | None:
        c = self.profile.get("contact", {})
        name = self.profile.get("name", "")
        parts = name.split()
        return {
            "first_name": parts[0] if parts else None,
            "last_name": " ".join(parts[1:]) if len(parts) > 1 else None,
            "full_name": name or None,
            "email": c.get("email") or None,
            "phone": c.get("phone") or None,
            "city": "Dubai" if "dubai" in (self.profile.get("location") or "").lower() else None,
        }.get(key)

    def answer(self, question: str, options: list[str] | None = None) -> Answer:
        q = re.sub(r"\s+", " ", (question or "")).strip()
        ql = q.lower()
        if not q:
            return Answer(q, None, False, "empty question label")
        for cat, pat in ALWAYS_STOP.items():
            if re.search(pat, ql):
                return Answer(q, None, False, f"{cat} question: always needs Anagha")
        for key, pat in CONTACT_FIELDS.items():
            if re.search(pat, ql) and len(ql) < 60:
                v = self.contact_value(key)
                if v:
                    return Answer(q, v, True, "contact detail from CV", f"contact:{key}")
                return Answer(q, None, False, f"{key} not set in config/candidate_private.yaml")
        for rule in self.rules:
            pats = rule.get("match") or []
            if any(re.search(p, ql, re.I) for p in pats):
                if rule.get("category") == "work_authorisation" and not rule.get("verified"):
                    return Answer(q, None, False, "work authorisation not verified", rule.get("id"))
                if not rule.get("verified") or rule.get("answer") in (None, ""):
                    return Answer(q, None, False, "answer not verified yet", rule.get("id"))
                ans = str(rule["answer"])
                if rule.get("type") == "yes_no" and not _is_yes_no(ql, options):
                    return Answer(q, None, False, "matched a yes/no rule but the question is not yes/no", rule.get("id"))
                if options:
                    match = _pick_option(ans, options)
                    if match is None:
                        return Answer(q, None, False, f"verified answer '{ans}' is not one of the options", rule.get("id"))
                    ans = match
                return Answer(q, ans, True, "verified answer", rule.get("id"))
        return Answer(q, None, False, "unknown question")


def _is_yes_no(ql: str, options: list[str] | None) -> bool:
    if options:
        return {o.strip().lower() for o in options} <= {"yes", "no"}
    return not re.match(r"(?:how|what|which|when|where|why|please (?:describe|explain|list|specify))\b", ql)


def _pick_option(ans: str, options: list[str]) -> str | None:
    a = ans.strip().lower()
    for o in options:
        if o.strip().lower() == a:
            return o
    for o in options:
        if o.strip().lower().startswith(a):
            return o
    return None
