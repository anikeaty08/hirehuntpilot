from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from hirehuntpilot.ai.adapter import AIAdapter
from hirehuntpilot.browser.session import BrowserSessionManager
from hirehuntpilot.config import ConfigManager, app_home
from hirehuntpilot.integrations.hirehunt_client import HireHuntClient
from hirehuntpilot.integrations.tracker import LocalTracker
from hirehuntpilot.portals import available_portals


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def run_doctor(config_manager: ConfigManager | None = None) -> list[CheckResult]:
    config_manager = config_manager or ConfigManager()
    config = config_manager.load()
    results: list[CheckResult] = []

    try:
        config_manager.load()
    except Exception as exc:
        results.append(CheckResult("config decrypt", False, str(exc)))
        return results
    results.append(CheckResult("config decrypt", True, "ok"))
    results.append(CheckResult("config backend", True, config_manager.crypto_backend()))

    issues = config_manager.validate(config)
    results.append(CheckResult("config fields", not issues, ", ".join(issues) if issues else "ok"))

    sqlite_path = Path(config.runtime.sqlite_path)
    results.append(CheckResult("sqlite path", sqlite_path.parent.exists(), str(sqlite_path)))
    results.append(CheckResult("local tracker path", True, str(app_home() / "applications.csv")))

    resume_path = Path(config.resume.json_path)
    results.append(CheckResult("resume json", resume_path.exists(), str(resume_path)))
    if config.resume.mode == "rendercv":
        rendercv_path = Path(config.resume.rendercv_path)
        results.append(CheckResult("rendercv yaml path", rendercv_path.parent.exists(), str(rendercv_path)))
        results.append(CheckResult("rendercv cli", shutil.which("rendercv") is not None, "rendercv executable"))

    browser = BrowserSessionManager()
    results.append(CheckResult("playwright available", browser.playwright_available(), "playwright import"))
    for portal in available_portals():
        ok, detail = browser.portal_session_valid(portal)
        results.append(CheckResult(f"{portal} session", ok, detail))

    ok, detail = LocalTracker().check_connection()
    results.append(CheckResult("local tracker", ok, detail))
    ok, detail = AIAdapter(config.ai).healthcheck()
    results.append(CheckResult("ai provider", ok, detail))

    client = HireHuntClient()
    try:
        jobs = client.search(
            query=config.preferences.role or "python developer",
            cities=config.preferences.cities,
            sources=config.preferences.sources,
            limit=1,
        )
    except Exception as exc:
        results.append(CheckResult("hirehunt search", False, str(exc)))
    else:
        results.append(CheckResult("hirehunt search", bool(jobs), f"returned {len(jobs)} jobs"))
    return results
