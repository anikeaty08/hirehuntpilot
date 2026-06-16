from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from hirehuntpilot.config import app_home
from hirehuntpilot.portals import PORTAL_DEFINITIONS


@dataclass(slots=True)
class SessionCaptureResult:
    ok: bool
    detail: str
    session_file: Path | None = None


LOGIN_SIGNALS: dict[str, tuple[str, ...]] = {
    "linkedin": (
        "a[href*='/feed/']",
        "img.global-nav__me-photo",
        "button[aria-label*='Me']",
        "[data-control-name='nav.settings']",
    ),
    "indeed": (
        "a[href*='/account']",
        "button[data-testid='AccountMenu']",
        "[data-testid='header-jobseeker-menu']",
    ),
    "internshala": (
        "a[href*='/student/dashboard']",
        "a[href*='/student/resume']",
        ".header_profile_image",
    ),
    "naukri": (
        ".nI-gNb-icon-img",
        "a[href*='mynaukri']",
        ".view-profile-wrapper",
    ),
    "unstop": (
        "a[href*='/u/']",
        "img[alt*='profile']",
        "[class*='profile']",
    ),
    "shine": (
        "a[href*='/myshine/']",
        "[class*='profile']",
        "[class*='avatar']",
    ),
}

LOGGED_OUT_SIGNALS: tuple[str, ...] = (
    "input[type='password']",
    "button:has-text('Sign in')",
    "button:has-text('Log in')",
    "text=Sign in",
    "text=Login",
)


class BrowserSessionManager:
    def __init__(self) -> None:
        self.sessions_root = app_home() / "sessions"
        self.sessions_root.mkdir(parents=True, exist_ok=True)

    def session_path(self, portal: str) -> Path:
        path = self.sessions_root / portal
        path.mkdir(parents=True, exist_ok=True)
        return path

    def refresh_session(
        self,
        portal: str,
        *,
        email: str = "",
        headed: bool = False,
        interactive: bool = False,
    ) -> tuple[bool, str]:
        if self.playwright_available() and headed and interactive and sys.stdin.isatty():
            result = self.capture_manual_session(portal, email=email)
            return result.ok, result.detail
        result = self._write_stub_session(portal, email=email, headed=headed)
        return result.ok, result.detail

    def capture_manual_session(self, portal: str, *, email: str = "") -> SessionCaptureResult:
        if not self.playwright_available():
            return self._write_stub_session(portal, email=email, headed=False)
        definition = PORTAL_DEFINITIONS.get(portal)
        if not definition:
            return SessionCaptureResult(False, f"unsupported portal: {portal}")
        login_url = definition.login_url
        portal_dir = self.session_path(portal)
        profile_dir = portal_dir / "profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        storage_state_path = portal_dir / "storage_state.json"
        session_file = portal_dir / "session.json"
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=False,
                    locale="en-IN",
                    timezone_id="Asia/Calcutta",
                )
                page = context.new_page()
                page.goto(login_url, wait_until="domcontentloaded")
                print("A browser window has been opened.")
                print(f"1. Log in to {definition.label}.")
                print("2. Complete any OTP/CAPTCHA.")
                print("3. Press ENTER here when finished.")
                try:
                    input()
                except EOFError:
                    context.close()
                    return self._write_stub_session(portal, email=email, headed=True)
                login_ok, reason = self._login_verified(context, page, portal)
                if not login_ok:
                    context.close()
                    return SessionCaptureResult(False, f"{portal} login not detected: {reason}")
                context.storage_state(path=str(storage_state_path))
                current_url = page.url
                context.close()
        except Exception as exc:  # pragma: no cover - browser dependent
            return SessionCaptureResult(False, str(exc))

        payload = {
            "portal": portal,
            "email": email,
            "mode": "playwright",
            "login_url": login_url,
            "current_url": current_url,
            "storage_state_path": str(storage_state_path),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        session_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return SessionCaptureResult(True, str(session_file), session_file=session_file)

    def playwright_available(self) -> bool:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True

    def portal_session_valid(self, portal: str) -> tuple[bool, str]:
        path = self.session_path(portal)
        session_file = path / "session.json"
        if not session_file.exists():
            if not self.playwright_available():
                return False, "playwright not installed"
            return False, f"no saved {portal} session"
        try:
            payload = json.loads(session_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "invalid session metadata"
        storage_state_path = payload.get("storage_state_path")
        if storage_state_path:
            if Path(storage_state_path).exists():
                if portal == "linkedin":
                    live_ok, live_detail = self._validate_linkedin_profile_session()
                    if not live_ok:
                        return False, live_detail
                    return True, live_detail
                return True, "playwright session data present"
            return False, "storage state file missing"
        if self.playwright_available():
            return True, "session data present"
        return True, "session stub present; playwright not installed"

    def profile_dir_path(self, portal: str) -> Path | None:
        profile_dir = self.session_path(portal) / "profile"
        if profile_dir.exists():
            return profile_dir
        return None

    def session_metadata(self, portal: str) -> dict[str, object] | None:
        session_file = self.session_path(portal) / "session.json"
        if not session_file.exists():
            return None
        try:
            payload = json.loads(session_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            return payload
        return None

    def storage_state_path(self, portal: str) -> Path | None:
        payload = self.session_metadata(portal)
        if not payload:
            return None
        raw_path = payload.get("storage_state_path")
        if not raw_path:
            return None
        path = Path(str(raw_path))
        if path.exists():
            return path
        return None

    def _write_stub_session(self, portal: str, *, email: str = "", headed: bool = False) -> SessionCaptureResult:
        path = self.session_path(portal) / "session.json"
        payload = {
            "portal": portal,
            "email": email,
            "headed": headed,
            "mode": "playwright" if self.playwright_available() else "stub",
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return SessionCaptureResult(True, str(path), session_file=path)

    def _login_verified(self, context, page, portal: str) -> tuple[bool, str]:
        portal_signals = LOGIN_SIGNALS.get(portal, ())
        pages = list(getattr(context, "pages", []) or [page])
        pages = list(reversed(pages))
        active_page = pages[0]

        for candidate in pages:
            if portal_signals and self._visible_any(candidate, portal_signals):
                return True, "portal authenticated UI detected"

        try:
            cookies = context.cookies()
        except Exception:
            cookies = []
        portal_cookies = [cookie for cookie in cookies if portal in str(cookie.get("domain", "")).casefold()]
        if len(portal_cookies) >= 1 or len(cookies) >= 3:
            return True, "browser session cookies detected"

        try:
            storage = active_page.evaluate(
                "() => ({local: window.localStorage.length, session: window.sessionStorage.length})"
            )
        except Exception:
            storage = {"local": 0, "session": 0}
        if int(storage.get("local", 0) or 0) > 0 or int(storage.get("session", 0) or 0) > 0:
            return True, "browser storage populated"

        if self._visible_any(active_page, LOGGED_OUT_SIGNALS):
            return False, "login form still visible"

        current_url = str(active_page.url).casefold()
        if any(marker in current_url for marker in ("login", "signin", "auth")):
            return False, f"still on auth URL {active_page.url}"

        return False, "no authenticated UI, cookies, or storage signals detected"

    def _visible_any(self, page, selectors: tuple[str, ...]) -> bool:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count() and locator.first.is_visible(timeout=1200):
                    return True
            except Exception:
                continue
        return False

    def _validate_linkedin_profile_session(self) -> tuple[bool, str]:
        profile_dir = self.profile_dir_path("linkedin")
        if profile_dir is None or not self.playwright_available():
            return True, "playwright session data present"
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=True,
                    locale="en-IN",
                    timezone_id="Asia/Calcutta",
                )
                page = context.new_page()
                page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1200)
                logged_out = self._visible_any(page, LOGGED_OUT_SIGNALS) or "linkedin.com/login" in str(page.url).casefold()
                context.close()
                if logged_out:
                    return False, "linkedin session requires relogin"
        except Exception as exc:
            return False, f"linkedin session validation failed: {exc}"
        return True, "linkedin session validated"
