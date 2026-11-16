import json
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own config, data and reports folders; real files are never touched."""
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg, ignore=shutil.ignore_patterns("settings.yaml", "screening_answers.yaml",
                                                                         "candidate_private.yaml"))
    (cfg / "candidate_private.yaml").write_text("email: test@example.invalid\nphone: '+971 00 000 0000'\n")
    monkeypatch.setenv("JOBBOT_CONFIG", str(cfg))
    monkeypatch.setenv("JOBBOT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("JOBBOT_REPORTS", str(tmp_path / "reports"))
    for k in ("ANTHROPIC_API_KEY", "EMAIL_ENABLED", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    if Path("/opt/pw-browsers/chromium").exists():
        monkeypatch.setenv("JOBBOT_BROWSER_EXECUTABLE", "/opt/pw-browsers/chromium")
    else:
        monkeypatch.setenv("JOBBOT_BROWSER_CHANNEL", "chromium")
    return tmp_path


@pytest.fixture
def sample_jobs():
    return json.loads((FIXTURES / "jobs" / "sample_jobs.json").read_text(encoding="utf-8"))


@pytest.fixture
def settings():
    from jobbot.config import load_settings
    s = load_settings()
    s["seconds_between_page_loads"] = 2
    return s
