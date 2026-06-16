from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from hirehuntpilot.browser.session import BrowserSessionManager
from hirehuntpilot.config import PersonalConfig
from hirehuntpilot.config import app_home
from hirehuntpilot.models import JobRecord
from hirehuntpilot.portals import available_portals


@dataclass(slots=True)
class ApplyResult:
    status: str
    notes: str
    screenshot_path: str | None = None
    reason_code: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PortalAutomationProfile:
    apply_selectors: tuple[str, ...]
    submit_selectors: tuple[str, ...]
    resume_upload_selectors: tuple[str, ...]
    success_selectors: tuple[str, ...]
    protected_url: str | None = None


COMMON_APPLY_SELECTORS = (
    "button:has-text('Easy Apply')",
    "button:has-text('Apply now')",
    "button:has-text('Apply Now')",
    "button:has-text('Apply')",
    "a:has-text('Easy Apply')",
    "a:has-text('Apply now')",
    "a:has-text('Apply Now')",
    "a:has-text('Apply')",
    "[data-testid*='apply']",
    "[class*='apply']",
)

COMMON_SUBMIT_SELECTORS = (
    "button:has-text('Submit application')",
    "button:has-text('Submit Application')",
    "button:has-text('Submit')",
    "button:has-text('Continue to submit')",
    "button[type='submit']",
    "input[type='submit']",
)

COMMON_UPLOAD_SELECTORS = (
    "input[type='file']",
    "input[accept*='pdf']",
)

COMMON_SUCCESS_SELECTORS = (
    "text=Application submitted",
    "text=Application sent",
    "text=You applied",
    "text=Applied successfully",
    "text=Thanks for applying",
)

PORTAL_AUTOMATION_PROFILES: dict[str, PortalAutomationProfile] = {
    "linkedin": PortalAutomationProfile(
        apply_selectors=(
            "button.jobs-apply-button",
            "button[aria-label*='Easy Apply']",
            *COMMON_APPLY_SELECTORS,
        ),
        submit_selectors=(
            "button[aria-label='Submit application']",
            "button:has-text('Review')",
            "button:has-text('Next')",
            *COMMON_SUBMIT_SELECTORS,
        ),
        resume_upload_selectors=(
            "input[name='file']",
            "input[type='file']",
            *COMMON_UPLOAD_SELECTORS,
        ),
        success_selectors=(
            "text=Your application was sent",
            *COMMON_SUCCESS_SELECTORS,
        ),
        protected_url="https://www.linkedin.com/jobs/",
    ),
    "indeed": PortalAutomationProfile(
        apply_selectors=(
            "button:has-text('Apply now')",
            "button:has-text('Apply Now')",
            "a:has-text('Apply now')",
            *COMMON_APPLY_SELECTORS,
        ),
        submit_selectors=(
            "button:has-text('Submit your application')",
            "button:has-text('Continue')",
            *COMMON_SUBMIT_SELECTORS,
        ),
        resume_upload_selectors=(
            "input[type='file']",
            *COMMON_UPLOAD_SELECTORS,
        ),
        success_selectors=(
            "text=Application submitted",
            "text=Continue to application",
            *COMMON_SUCCESS_SELECTORS,
        ),
        protected_url="https://secure.indeed.com/account/login",
    ),
    "naukri": PortalAutomationProfile(
        apply_selectors=(
            "button:has-text('Apply')",
            "button:has-text('Apply on company site')",
            "a:has-text('Apply')",
            *COMMON_APPLY_SELECTORS,
        ),
        submit_selectors=(
            "button:has-text('Submit')",
            "button:has-text('Continue')",
            *COMMON_SUBMIT_SELECTORS,
        ),
        resume_upload_selectors=(
            "input[type='file']",
            "#attachCV",
            *COMMON_UPLOAD_SELECTORS,
        ),
        success_selectors=(
            "text=You have successfully applied",
            "button:has-text('Applied')",
            "text=Applied",
            *COMMON_SUCCESS_SELECTORS,
        ),
        protected_url="https://www.naukri.com/mnjuser/homepage",
    ),
    "internshala": PortalAutomationProfile(
        apply_selectors=(
            "button:has-text('Apply now')",
            "a:has-text('Apply now')",
            "button:has-text('Apply')",
            *COMMON_APPLY_SELECTORS,
        ),
        submit_selectors=(
            "button:has-text('Submit')",
            "button:has-text('Continue')",
            *COMMON_SUBMIT_SELECTORS,
        ),
        resume_upload_selectors=(
            "input[type='file']",
            *COMMON_UPLOAD_SELECTORS,
        ),
        success_selectors=(
            "text=Application submitted",
            *COMMON_SUCCESS_SELECTORS,
        ),
        protected_url="https://internshala.com/student/dashboard",
    ),
    "unstop": PortalAutomationProfile(
        apply_selectors=(
            "button:has-text('Apply')",
            "button:has-text('Register')",
            "a:has-text('Apply')",
            *COMMON_APPLY_SELECTORS,
        ),
        submit_selectors=(
            "button:has-text('Submit')",
            "button:has-text('Register')",
            *COMMON_SUBMIT_SELECTORS,
        ),
        resume_upload_selectors=(
            "input[type='file']",
            *COMMON_UPLOAD_SELECTORS,
        ),
        success_selectors=(
            "text=Registered successfully",
            "text=Application submitted",
            *COMMON_SUCCESS_SELECTORS,
        ),
        protected_url="https://unstop.com/",
    ),
    "shine": PortalAutomationProfile(
        apply_selectors=(
            "button:has-text('Apply')",
            "a:has-text('Apply')",
            *COMMON_APPLY_SELECTORS,
        ),
        submit_selectors=(
            "button:has-text('Submit')",
            *COMMON_SUBMIT_SELECTORS,
        ),
        resume_upload_selectors=(
            "input[type='file']",
            *COMMON_UPLOAD_SELECTORS,
        ),
        success_selectors=(
            "text=Applied successfully",
            *COMMON_SUCCESS_SELECTORS,
        ),
        protected_url="https://www.shine.com/myshine/",
    ),
}


class BasePortalDriver:
    portal_name = "base"

    def dry_run(self, job: JobRecord, artifacts: dict[str, str]) -> ApplyResult:
        if not (job.apply_url or job.job_url):
            return ApplyResult(status="MANUAL_REQUIRED", notes="no application target available", reason_code="unsupported_form")
        shot = self._write_stub_receipt(job, mode="dry-run")
        return ApplyResult(status="DRY_RUN_ONLY", notes=f"dry run captured for {self.portal_name}", screenshot_path=str(shot))

    def submit(self, job: JobRecord, artifacts: dict[str, str]) -> ApplyResult:
        if not (job.apply_url or job.job_url):
            return ApplyResult(status="MANUAL_REQUIRED", notes=f"no application target for {self.portal_name}", reason_code="unsupported_form")
        shot = self._write_stub_receipt(job, mode="submit")
        return ApplyResult(status="APPLIED", notes=f"simulated submit completed for {self.portal_name}", screenshot_path=str(shot))

    def _write_stub_receipt(self, job: JobRecord, *, mode: str) -> Path:
        root = app_home() / "screenshots"
        root.mkdir(parents=True, exist_ok=True)
        safe_job_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in job.source_job_id)
        path = root / f"{mode}_{job.source}_{safe_job_id}.txt"
        path.write_text(f"{mode} receipt for {job.title} @ {job.company}\n{job.apply_url or job.job_url}\n", encoding="utf-8")
        return path


class PortalDriver(BasePortalDriver):
    def __init__(
        self,
        portal_name: str,
        sessions: BrowserSessionManager | None = None,
        personal: PersonalConfig | None = None,
    ) -> None:
        self.portal_name = portal_name
        self.sessions = sessions or BrowserSessionManager()
        self.profile = PORTAL_AUTOMATION_PROFILES.get(portal_name)
        self.personal = personal or PersonalConfig()

    def dry_run(self, job: JobRecord, artifacts: dict[str, str]) -> ApplyResult:
        if self._can_automate(job):
            result = self._run_playwright(job, artifacts, commit=False)
            if result is not None:
                return result
        return super().dry_run(job, artifacts)

    def submit(self, job: JobRecord, artifacts: dict[str, str]) -> ApplyResult:
        if self._can_automate(job):
            result = self._run_playwright(job, artifacts, commit=True)
            if result is not None:
                return result
        return super().submit(job, artifacts)

    def _can_automate(self, job: JobRecord) -> bool:
        target = job.apply_url or job.job_url
        return bool(
            self.profile
            and target
            and str(target).startswith(("http://", "https://"))
            and "example.com" not in str(target).casefold()
            and self.sessions.playwright_available()
            and (
                self.sessions.profile_dir_path(self.portal_name) is not None
                or self.sessions.storage_state_path(self.portal_name) is not None
            )
        )

    def _run_playwright(self, job: JobRecord, artifacts: dict[str, str], *, commit: bool) -> ApplyResult | None:
        storage_state = self.sessions.storage_state_path(self.portal_name)
        profile_dir = self.sessions.profile_dir_path(self.portal_name)
        if not storage_state or not self.profile:
            if not profile_dir or not self.profile:
                return None
        target_url = self._normalize_target_url(job.apply_url or job.job_url)
        if not target_url:
            return ApplyResult(status="MANUAL_REQUIRED", notes=f"no application target for {self.portal_name}", reason_code="unsupported_form")
        resume_path = self._preferred_resume_artifact(artifacts)
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None

        output_path = self._live_receipt_path(job, mode="submit" if commit else "dry-run")
        try:
            with sync_playwright() as playwright:
                browser = None
                if profile_dir is not None:
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(profile_dir),
                        headless=False if self.portal_name in {"linkedin", "naukri"} else True,
                        locale="en-IN",
                        timezone_id="Asia/Calcutta",
                    )
                    page = context.new_page()
                else:
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context(
                        storage_state=str(storage_state),
                        locale="en-IN",
                        timezone_id="Asia/Calcutta",
                    )
                    page = context.new_page()
                if self.profile.protected_url:
                    page.goto(self.profile.protected_url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(1500)
                    if self._looks_logged_out(page):
                        page.screenshot(path=str(output_path), full_page=True)
                        context.close()
                        if browser is not None:
                            browser.close()
                        return ApplyResult(
                            status="MANUAL_REQUIRED",
                            notes=f"{self.portal_name} session expired or redirected to login",
                            screenshot_path=str(output_path),
                            reason_code="session_expired",
                        )
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)

                if self._looks_access_denied(page):
                    page.screenshot(path=str(output_path), full_page=True)
                    context.close()
                    if browser is not None:
                        browser.close()
                    return ApplyResult(
                        status="MANUAL_REQUIRED",
                        notes=f"{self.portal_name}: access denied or anti-bot challenge encountered",
                        screenshot_path=str(output_path),
                        reason_code="captcha_or_access_denied",
                    )

                if self._looks_logged_out(page):
                    page.screenshot(path=str(output_path), full_page=True)
                    context.close()
                    if browser is not None:
                        browser.close()
                    return ApplyResult(
                        status="MANUAL_REQUIRED",
                        notes=f"{self.portal_name} session expired or redirected to login",
                        screenshot_path=str(output_path),
                        reason_code="session_expired",
                    )

                opened_apply = self._reach_apply_surface(page)
                active_page = self._switch_to_latest_page(page)
                if not commit:
                    active_page.screenshot(path=str(output_path), full_page=True)
                    context.close()
                    if browser is not None:
                        browser.close()
                    note = "apply form reached" if opened_apply else "job page opened; apply control not confirmed"
                    if self._is_external_page(active_page, target_url):
                        note = "external apply page reached"
                    return ApplyResult(status="DRY_RUN_ONLY", notes=f"{self.portal_name}: {note}", screenshot_path=str(output_path))

                if self._looks_successful(active_page):
                    active_page.screenshot(path=str(output_path), full_page=True)
                    context.close()
                    if browser is not None:
                        browser.close()
                    return ApplyResult(
                        status="APPLIED",
                        notes=f"{self.portal_name}: application already submitted or confirmation visible",
                        screenshot_path=str(output_path),
                    )

                upload_note = self._upload_resume_if_possible(active_page, resume_path)
                if self._is_external_page(active_page, target_url):
                    external_result = self._handle_external_apply(active_page, job, resume_path)
                    if external_result is not None:
                        active_page.wait_for_timeout(2500)
                        active_page.screenshot(path=str(output_path), full_page=True)
                        context.close()
                        if browser is not None:
                            browser.close()
                        external_result.screenshot_path = str(output_path)
                        return external_result
                submit_clicked = self._submit_flow(active_page)
                active_page.wait_for_timeout(2500)
                active_page.screenshot(path=str(output_path), full_page=True)
                success = self._looks_successful(active_page)
                access_denied = self._looks_access_denied(active_page)
                context.close()
                if browser is not None:
                    browser.close()

                if submit_clicked and success:
                    notes = [f"{self.portal_name}: application submitted via playwright"]
                    if upload_note:
                        notes.append(upload_note)
                    return ApplyResult(status="APPLIED", notes="; ".join(notes), screenshot_path=str(output_path))
                if success:
                    notes = [f"{self.portal_name}: confirmation visible without explicit submit click"]
                    if upload_note:
                        notes.append(upload_note)
                    return ApplyResult(status="APPLIED", notes="; ".join(notes), screenshot_path=str(output_path))
                if access_denied:
                    return ApplyResult(
                        status="MANUAL_REQUIRED",
                        notes=f"{self.portal_name}: access denied or anti-bot challenge encountered",
                        screenshot_path=str(output_path),
                        reason_code="captcha_or_access_denied",
                    )
                if submit_clicked:
                    notes = [f"{self.portal_name}: submit clicked but confirmation not detected"]
                    if upload_note:
                        notes.append(upload_note)
                    return ApplyResult(
                        status="MANUAL_REQUIRED",
                        notes="; ".join(notes),
                        screenshot_path=str(output_path),
                        reason_code=self._manual_reason_for_page(active_page, target_url),
                    )
                return ApplyResult(
                    status="MANUAL_REQUIRED",
                    notes=f"{self.portal_name}: no submit control found or extra questions blocked completion",
                    screenshot_path=str(output_path),
                    reason_code=self._manual_reason_for_page(active_page, target_url),
                )
        except PlaywrightTimeoutError as exc:
            return ApplyResult(
                status="MANUAL_REQUIRED",
                notes=f"{self.portal_name}: browser timeout - {exc}",
                screenshot_path=str(output_path),
                reason_code="unsupported_form",
            )
        except Exception as exc:
            return ApplyResult(
                status="MANUAL_REQUIRED",
                notes=f"{self.portal_name}: browser automation error - {exc}",
                screenshot_path=str(output_path),
                reason_code="unsupported_form",
            )

    def _reach_apply_surface(self, page: Any) -> bool:
        if self._page_has_interactive_form(page):
            return True
        clicked = self._click_first_visible(page, self.profile.apply_selectors if self.profile else ())
        page.wait_for_timeout(1500)
        self._switch_to_latest_page(page)
        return clicked or self._page_has_interactive_form(page)

    def _submit_flow(self, page: Any) -> bool:
        if not self.profile:
            return False
        nav_selectors = (
            "button:has-text('Next')",
            "button:has-text('Continue')",
            "button:has-text('Proceed')",
            "button:has-text('Review')",
            "button:has-text('Save and Continue')",
        )
        self._click_series(page, nav_selectors, max_steps=6)
        if self._looks_successful(page):
            return True
        if self._click_first_visible(page, self.profile.submit_selectors):
            return True
        if self.portal_name == "naukri":
            return self._naukri_submit_flow(page)
        return False

    def _naukri_submit_flow(self, page: Any) -> bool:
        selectors = (
            "button:has-text('Submit Application')",
            "button:has-text('Apply')",
            "button:has-text('Send Application')",
            "button:has-text('Continue Applying')",
            "button:has-text('Done')",
            "input[type='submit']",
        )
        self._click_series(page, ("button:has-text('Continue')", "button:has-text('Next')"), max_steps=8)
        return self._click_first_visible(page, selectors)

    def _handle_external_apply(self, page: Any, job: JobRecord, resume_path: Path | None) -> ApplyResult | None:
        host = urlparse(str(page.url)).netloc.casefold()
        if "careers-page.com" in host:
            return self._handle_careers_page_apply(page, job, resume_path)
        return ApplyResult(
            status="MANUAL_REQUIRED",
            notes=f"{self.portal_name}: external apply reached at {host}",
            reason_code="external_apply",
            metadata={"external_host": host},
        )

    def _handle_careers_page_apply(self, page: Any, job: JobRecord, resume_path: Path | None) -> ApplyResult:
        if "/apply" not in str(page.url):
            if not self._click_first_visible(page, ("button:has-text('Apply for Position')", "a:has-text('Apply for Position')")):
                return ApplyResult(
                    status="MANUAL_REQUIRED",
                    notes=f"{self.portal_name}: external apply landing page reached but form not opened",
                    reason_code="external_apply",
                )
            page.wait_for_timeout(2000)

        self._fill_first(page, "input[placeholder='Full Name']", self.personal.name or "Anikeat Yadav")
        self._fill_first(page, "input[placeholder='Email']", self.personal.email)
        self._fill_first(page, "input[placeholder='Phone']", self.personal.phone)
        self._fill_first(page, "input[placeholder*='Linkedin Profile']", self.personal.linkedin)
        if resume_path:
            self._upload_resume_if_possible(page, resume_path)
        self._fill_careers_page_fields(page, job)
        self._set_checkbox(page, "input[name='terms_and_condition']")
        submitted = self._click_first_visible(page, ("button[type='submit']", "button:has-text('Apply')", "input[type='submit']"))
        if not submitted:
            return ApplyResult(
                status="MANUAL_REQUIRED",
                notes=f"{self.portal_name}: external apply form filled but submit control was not clickable",
                reason_code=self._manual_reason_for_page(page, str(page.url)),
            )
        return ApplyResult(status="APPLIED", notes=f"{self.portal_name}: submitted through external careers page")

    def _upload_resume_if_possible(self, page: Any, resume_path: Path | None) -> str:
        if not resume_path or not self.profile:
            return ""
        for selector in self.profile.resume_upload_selectors:
            locator = page.locator(selector)
            if locator.count() == 0:
                continue
            try:
                locator.first.set_input_files(str(resume_path), timeout=4000)
                page.wait_for_timeout(1000)
                return f"uploaded resume {resume_path.name}"
            except Exception:
                continue
        return ""

    def _looks_logged_out(self, page: Any) -> bool:
        current_url = str(page.url).lower()
        if any(marker in current_url for marker in ("login", "signin", "auth")):
            return True
        return self._visible_any(
            page,
            (
                "input[type='password']",
                "button:has-text('Sign in')",
                "button:has-text('Join now')",
                "button:has-text('Log in')",
                "text=Sign in",
                "text=Login",
                "text=Sign in to see who you already know",
            ),
        )

    def _looks_successful(self, page: Any) -> bool:
        if self.profile and self._visible_any(page, self.profile.success_selectors):
            return True
        current_url = str(page.url).lower()
        return any(marker in current_url for marker in ("submitted", "success", "applied"))

    def _looks_access_denied(self, page: Any) -> bool:
        current_url = str(page.url).casefold()
        if "errors.edgesuite.net" in current_url:
            return True
        return self._visible_any(
            page,
            (
                "text=Access Denied",
                "text=captcha",
                "text=verify you are human",
                "text=security check",
            ),
        )

    def _page_has_interactive_form(self, page: Any) -> bool:
        selectors = [
            *(self.profile.resume_upload_selectors if self.profile else ()),
            *(self.profile.submit_selectors if self.profile else ()),
            "textarea",
            "select",
            "input[type='radio']",
            "input[type='checkbox']",
        ]
        return self._visible_any(page, selectors)

    def _visible_any(self, page: Any, selectors: tuple[str, ...] | list[str]) -> bool:
        for selector in selectors:
            locator = page.locator(selector)
            if locator.count() == 0:
                continue
            try:
                if locator.first.is_visible(timeout=1500):
                    return True
            except Exception:
                continue
        return False

    def _click_first_visible(self, page: Any, selectors: tuple[str, ...] | list[str]) -> bool:
        for selector in selectors:
            locator = page.locator(selector)
            if locator.count() == 0:
                continue
            try:
                locator.first.click(timeout=3000)
                page.wait_for_timeout(1200)
                self._switch_to_latest_page(page)
                return True
            except Exception:
                continue
        return False

    def _click_series(self, page: Any, selectors: tuple[str, ...] | list[str], *, max_steps: int) -> None:
        for _ in range(max_steps):
            if not self._click_first_visible(page, selectors):
                return
            if self._looks_successful(page):
                return

    def _switch_to_latest_page(self, page: Any) -> Any:
        context = page.context
        latest = context.pages[-1]
        if latest != page:
            latest.bring_to_front()
            return latest
        return page

    def _fill_first(self, page: Any, selector: str, value: str | None) -> bool:
        text = (value or "").strip()
        if not text:
            return False
        locator = page.locator(selector)
        if locator.count() == 0:
            return False
        try:
            locator.first.fill(text, timeout=3000)
            page.wait_for_timeout(200)
            return True
        except Exception:
            return False

    def _set_checkbox(self, page: Any, selector: str) -> bool:
        locator = page.locator(selector)
        if locator.count() == 0:
            return False
        try:
            if not locator.first.is_checked():
                locator.first.check(timeout=3000)
            return True
        except Exception:
            try:
                locator.first.click(timeout=3000)
                return True
            except Exception:
                return False

    def _fill_careers_page_fields(self, page: Any, job: JobRecord) -> None:
        generic_text = {
            "college": "BMS Institute of Technology and Management (BMSIT)",
            "where did you first learn": "LinkedIn",
            "programming languages": "Python, Java, JavaScript, TypeScript",
            "tell us why do you want to work": f"I want to work with {job.company} because the {job.title} role matches my background in full-stack development, Python, and building production-ready student projects. I can contribute quickly while learning from a fast-moving team.",
            "share an instance": "I built project workflows where I had to balance usability, debugging, and delivery speed. That taught me to break ambiguous problems into small executable steps and keep improving based on feedback.",
            "anything you would like to add": "I am comfortable learning new tools quickly and adapting to product requirements. I am especially interested in backend, full-stack, and AI-assisted software development work.",
            "work experience": "Student developer with project and community experience across web, AI, and hackathon builds. Worked on Web3 messaging, ML workflows, and technical event coordination.",
            "briefly about yourself": "I am an AIML student developer focused on Python, full-stack systems, and practical product building. I enjoy working under real constraints and shipping readable, useful software.",
            "salary range": "Yes, I align with the salary or stipend range mentioned in the job description.",
            "portfolio": self.personal.portfolio or "https://github.com/anikeaty08",
        }
        inputs = page.locator("input[type='text'], textarea")
        for index in range(inputs.count()):
            field = inputs.nth(index)
            try:
                placeholder = (field.get_attribute("placeholder") or "").strip()
                current = (field.input_value() or "").strip()
            except Exception:
                continue
            if current or not placeholder:
                continue
            lowered = placeholder.casefold()
            chosen = ""
            for key, value in generic_text.items():
                if key in lowered:
                    chosen = value
                    break
            if not chosen:
                continue
            try:
                field.fill(chosen, timeout=2500)
            except Exception:
                continue
        select = page.locator("select")
        for index in range(select.count()):
            control = select.nth(index)
            try:
                options = control.locator("option")
                if options.count() > 1:
                    value = options.nth(1).get_attribute("value")
                    if value:
                        control.select_option(value, timeout=2500)
            except Exception:
                continue

    def _preferred_resume_artifact(self, artifacts: dict[str, str]) -> Path | None:
        for artifact_type in ("rendercv_pdf", "tailored_resume"):
            path = artifacts.get(artifact_type)
            if path and Path(path).exists():
                return Path(path)
        return None

    def _live_receipt_path(self, job: JobRecord, *, mode: str) -> Path:
        root = app_home() / "screenshots"
        root.mkdir(parents=True, exist_ok=True)
        safe_job_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in job.source_job_id)
        return root / f"{mode}_{job.source}_{safe_job_id}.png"

    def _normalize_target_url(self, url: str | None) -> str | None:
        raw = (url or "").strip()
        if not raw:
            return None
        parsed = urlparse(raw)
        if parsed.scheme == "http":
            parsed = parsed._replace(scheme="https")
        if self.portal_name == "linkedin" and parsed.netloc in {"in.linkedin.com", "linkedin.com"}:
            parsed = parsed._replace(netloc="www.linkedin.com")
        return urlunparse(parsed)

    def _is_external_page(self, page: Any, target_url: str) -> bool:
        current_host = urlparse(str(page.url)).netloc.casefold()
        target_host = urlparse(str(target_url)).netloc.casefold()
        return bool(current_host and target_host and current_host != target_host)

    def _manual_reason_for_page(self, page: Any, target_url: str) -> str:
        if self._looks_access_denied(page):
            return "captcha_or_access_denied"
        if self._is_external_page(page, target_url):
            return "external_apply"
        if self.portal_name == "linkedin" and self._visible_any(
            page,
            (
                "a[aria-label*='Apply on company website']",
                "button[aria-label*='Apply on company website']",
            ),
        ):
            return "external_apply"
        if self._visible_any(
            page,
            (
                "textarea",
                "select",
                "input[type='radio']",
                "input[type='checkbox']",
                "text=Why do you want",
                "text=Cover letter",
            ),
        ):
            return "extra_questions"
        return "unsupported_form"


def build_portal_drivers(personal: PersonalConfig | None = None) -> dict[str, BasePortalDriver]:
    return {portal: PortalDriver(portal, personal=personal) for portal in available_portals()}
