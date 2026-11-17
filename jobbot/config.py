"""Paths, settings and candidate profile loading."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(os.environ.get("JOBBOT_HOME", Path(__file__).resolve().parent.parent))
CONFIG_DIR = ROOT / "config"
DATA_DIR = Path(os.environ.get("JOBBOT_DATA", ROOT / "data"))
REPORTS_DIR = Path(os.environ.get("JOBBOT_REPORTS", ROOT / "reports"))

load_dotenv(ROOT / ".env")

VALID_MODES = ("review", "auto")


@dataclass(frozen=True)
class Paths:
    root: Path = ROOT
    config: Path = CONFIG_DIR
    data: Path = DATA_DIR
    reports: Path = REPORTS_DIR

    @property
    def db(self) -> Path:
        return self.data / "jobbot.sqlite3"

    @property
    def backups(self) -> Path:
        return self.data / "backups"

    @property
    def documents(self) -> Path:
        return self.data / "applications"

    @property
    def screenshots(self) -> Path:
        return self.data / "screenshots"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def cv_dir(self) -> Path:
        return self.data / "cv"

    @property
    def settings_file(self) -> Path:
        return self.config / "settings.yaml"

    @property
    def answers_file(self) -> Path:
        return self.config / "screening_answers.yaml"

    def ensure(self) -> None:
        for p in (self.data, self.backups, self.documents, self.screenshots, self.logs,
                  self.cv_dir, self.reports / "daily", self.reports / "weekly"):
            p.mkdir(parents=True, exist_ok=True)


def paths() -> Paths:
    # Re-read env so tests can point JOBBOT_DATA somewhere else.
    return Paths(
        root=ROOT,
        config=Path(os.environ.get("JOBBOT_CONFIG", CONFIG_DIR)),
        data=Path(os.environ.get("JOBBOT_DATA", DATA_DIR)),
        reports=Path(os.environ.get("JOBBOT_REPORTS", REPORTS_DIR)),
    )


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def default_settings() -> dict:
    return _read_yaml(ROOT / "config" / "settings.example.yaml")


def load_settings() -> dict:
    p = paths()
    s = _deep_merge(default_settings(), _read_yaml(p.settings_file))
    validate_settings(s)
    return s


def validate_settings(s: dict) -> None:
    if s.get("application_mode") not in VALID_MODES:
        raise ValueError(f"application_mode must be one of {VALID_MODES}")
    for key, lo, hi in (("match_threshold", 0, 100), ("review_threshold", 0, 100),
                        ("daily_application_limit", 0, 50), ("minimum_salary_aed", 0, 10_000_000),
                        ("seconds_between_page_loads", 2, 120)):
        v = s.get(key)
        if not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise ValueError(f"{key} must be a number between {lo} and {hi}")
    if not s.get("locations"):
        raise ValueError("at least one search location is needed")


def save_settings(s: dict) -> None:
    validate_settings(s)
    p = paths()
    p.settings_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.settings_file.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(s, f, sort_keys=False, allow_unicode=True)
    tmp.replace(p.settings_file)


def rules_fingerprint(s: dict, answers: dict | None = None) -> str:
    """Hash of everything that decides what gets submitted. Changing any of it voids authorisation."""
    relevant = {
        "match_threshold": s.get("match_threshold"),
        "daily_application_limit": s.get("daily_application_limit"),
        "minimum_salary_aed": s.get("minimum_salary_aed"),
        "job_titles": s.get("job_titles"),
        "locations": s.get("locations"),
        "answers": answers if answers is not None else load_answers(),
    }
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, default=str).encode()).hexdigest()[:16]


def auto_submit_allowed(s: dict) -> tuple[bool, str]:
    if s.get("application_mode") != "auto":
        return False, "application mode is review"
    a = s.get("authorisation") or {}
    if not a.get("authorised"):
        return False, "auto-apply rules have not been authorised by Anagha (run: python -m jobbot authorise)"
    if a.get("rules_fingerprint") != rules_fingerprint(s):
        return False, "settings or screening answers changed since authorisation; authorise again"
    return True, "authorised"


def load_profile() -> dict:
    p = paths()
    profile = _read_yaml(p.config / "candidate_profile.yaml")
    private = _read_yaml(p.config / "candidate_private.yaml")
    profile["contact"] = {k: private.get(k, "") for k in ("email", "phone", "linkedin", "aapc_id")}
    return profile


def load_answers() -> dict:
    p = paths()
    f = p.answers_file if p.answers_file.exists() else ROOT / "config" / "screening_answers.example.yaml"
    return _read_yaml(f)


def init_files() -> list[str]:
    """Create local config files from examples without overwriting anything."""
    p = paths()
    p.ensure()
    created = []
    for example, target in (("settings.example.yaml", "settings.yaml"),
                            ("screening_answers.example.yaml", "screening_answers.yaml"),
                            ("candidate_private.example.yaml", "candidate_private.yaml")):
        dst = p.config / target
        if not dst.exists():
            shutil.copy(ROOT / "config" / example, dst)
            created.append(str(dst))
    env = ROOT / ".env"
    if not env.exists() and (ROOT / ".env.example").exists():
        shutil.copy(ROOT / ".env.example", env)
        created.append(str(env))
    return created


def env(name: str, default: Any = None) -> Any:
    v = os.environ.get(name)
    return v if v not in (None, "") else default
