"""Job listings are untrusted input. Clean them and flag text that tries to steer an AI or the bot."""
from __future__ import annotations

import html
import re

MAX_DESCRIPTION_CHARS = 20_000

_INJECTION_PATTERNS = [
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above) (?:instructions|prompts?)",
    r"disregard (?:all |any )?(?:previous|prior|above)",
    r"\bsystem prompt\b",
    r"you are (?:now )?(?:an? )?(?:ai|assistant|chatgpt|claude|language model)",
    r"\b(?:ai|llm|chatgpt|claude|gpt)\b.{0,40}\b(?:must|should|need to)\b",
    r"(?:reveal|send|share|email|provide) (?:your |the )?(?:password|credentials|api key|passport|bank|otp)",
    r"if you are an? (?:ai|bot|language model)",
    r"new instructions?:",
    r"<\s*/?\s*(?:system|assistant|instructions?)\s*>",
]
_INJ = re.compile("|".join(_INJECTION_PATTERNS), re.I | re.S)


def clean_text(text: str | None, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    if not text:
        return ""
    t = html.unescape(text)
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "\n- ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    # strip zero-width and control characters that can hide text
    t = re.sub(r"[​-‏‪-‮⁠-⁤﻿]", "", t)
    t = re.sub(r"[^\S\n]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip()[:limit]


def clean_field(text: str | None, limit: int = 200) -> str:
    return re.sub(r"\s+", " ", clean_text(text, limit * 2)).strip()[:limit]


def injection_flags(text: str | None) -> list[str]:
    if not text:
        return []
    return sorted({m.group(0).strip()[:80] for m in _INJ.finditer(text)})


def strip_injections(text: str | None) -> tuple[str, list[str]]:
    """Remove sentences that try to instruct an AI or ask for secrets. Returns (clean text, removed bits)."""
    if not text:
        return "", []
    removed: list[str] = []
    kept_lines = []
    for line in text.splitlines():
        parts = re.split(r"(?<=[.!?])\s+", line)
        keep = []
        for p in parts:
            if _INJ.search(p):
                removed.append(p.strip()[:200])
            else:
                keep.append(p)
        kept_lines.append(" ".join(keep))
    return "\n".join(kept_lines).strip(), removed
