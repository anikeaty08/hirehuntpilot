from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hirehuntpilot.ai.adapter import AIAdapter
from hirehuntpilot.browser.session import BrowserSessionManager
from hirehuntpilot.config import AppConfig


@dataclass(slots=True)
class SetupCheck:
    key: str
    ok: bool
    detail: str


def evaluate_setup(config: AppConfig) -> list[SetupCheck]:
    checks: list[SetupCheck] = []

    profile_ok = bool(config.personal.name and config.personal.email)
    checks.append(SetupCheck("profile", profile_ok, "personal identity saved" if profile_ok else "missing name or email"))

    resume_ok = bool(config.resume.json_path and Path(config.resume.json_path).exists())
    checks.append(SetupCheck("resume", resume_ok, config.resume.json_path or "resume json path missing"))

    ai_ok, ai_detail = AIAdapter(config.ai).healthcheck()
    checks.append(SetupCheck("ai", ai_ok, ai_detail))

    notify_ok = config.telegram.enabled or config.whatsapp.enabled
    notify_detail = "remote notification enabled" if notify_ok else "notifications optional; local logging only"
    checks.append(SetupCheck("notifications", True, notify_detail))

    sessions = BrowserSessionManager()
    for portal in config.preferences.sources:
        ok, detail = sessions.portal_session_valid(portal)
        checks.append(SetupCheck(f"portal.{portal}", ok, detail))

    return checks


def ready_for_run(config: AppConfig) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if not config.personal.email:
        issues.append("personal.email missing")
    if not config.preferences.role:
        issues.append("preferences.role missing")
    if not config.preferences.sources:
        issues.append("no job portals enabled")
    if not config.resume.json_path or not Path(config.resume.json_path).exists():
        issues.append("resume profile missing")
    return (not issues), issues


def ready_for_prepare(config: AppConfig) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if not config.resume.json_path or not Path(config.resume.json_path).exists():
        issues.append("resume profile missing")
    if config.resume.mode == "rendercv" and not config.resume.rendercv_path:
        issues.append("rendercv output path missing")
    if config.ai.provider in {"", "none"}:
        issues.append("ai setup incomplete: no provider configured")
        return (not issues), issues
    ai_ok, ai_detail = AIAdapter(config.ai).healthcheck()
    if not ai_ok:
        issues.append(f"ai setup incomplete: {ai_detail}")
    return (not issues), issues
