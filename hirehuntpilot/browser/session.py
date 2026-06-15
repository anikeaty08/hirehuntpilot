from __future__ import annotations

import json
from pathlib import Path

from hirehuntpilot.config import app_home


class BrowserSessionManager:
    def __init__(self) -> None:
        self.sessions_root = app_home() / "sessions"
        self.sessions_root.mkdir(parents=True, exist_ok=True)

    def session_path(self, portal: str) -> Path:
        path = self.sessions_root / portal
        path.mkdir(parents=True, exist_ok=True)
        return path

    def refresh_session(self, portal: str, *, email: str = "", headed: bool = False) -> tuple[bool, str]:
        path = self.session_path(portal) / "session.json"
        payload = {
            "portal": portal,
            "email": email,
            "headed": headed,
            "mode": "playwright" if self.playwright_available() else "stub",
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return True, str(path)

    def playwright_available(self) -> bool:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True

    def portal_session_valid(self, portal: str) -> tuple[bool, str]:
        path = self.session_path(portal)
        session_file = path / "session.json"
        if session_file.exists():
            if self.playwright_available():
                return True, "session data present"
            return True, "session stub present; playwright not installed"
        if not self.playwright_available():
            return False, "playwright not installed"
        return False, f"no saved {portal} session"
