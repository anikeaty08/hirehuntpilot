import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from hirehuntpilot.browser.portals import build_portal_drivers
from hirehuntpilot.browser.session import BrowserSessionManager
from hirehuntpilot.models import JobRecord
from hirehuntpilot.portals import available_portals


class PortalDriverTests(unittest.TestCase):
    def test_builds_driver_for_every_supported_portal(self) -> None:
        drivers = build_portal_drivers()
        self.assertEqual(set(drivers.keys()), set(available_portals()))

    def test_fallback_dry_run_and_submit_work_for_all_supported_portals(self) -> None:
        drivers = build_portal_drivers()
        for portal, driver in drivers.items():
            job = JobRecord(
                source_job_id=f"{portal}:demo",
                title="Python Developer",
                company="Demo Co",
                source=portal,
                job_url=f"https://example.com/{portal}/job",
                apply_url=f"https://example.com/{portal}/apply",
            )
            dry_run = driver.dry_run(job, {})
            submit = driver.submit(job, {})
            self.assertEqual(dry_run.status, "DRY_RUN_ONLY")
            self.assertEqual(submit.status, "APPLIED")

    def test_normalizes_http_target_url_to_https(self) -> None:
        driver = build_portal_drivers()["naukri"]
        self.assertEqual(
            driver._normalize_target_url("http://www.naukri.com/job-listings-demo"),
            "https://www.naukri.com/job-listings-demo",
        )

    def test_can_automate_with_profile_dir_only(self) -> None:
        with TemporaryDirectory() as tmp:
            sessions = BrowserSessionManager()
            sessions.sessions_root = Path(tmp)
            portal_dir = sessions.session_path("linkedin")
            (portal_dir / "profile").mkdir(parents=True, exist_ok=True)
            driver = build_portal_drivers()["linkedin"]
            driver.sessions = sessions
            job = JobRecord(
                source_job_id="linkedin:demo",
                title="Python Developer",
                company="Demo Co",
                source="linkedin",
                job_url="https://www.linkedin.com/jobs/view/123",
            )
            self.assertTrue(driver._can_automate(job))

    def test_classifies_access_denied_as_captcha_or_access_denied(self) -> None:
        driver = build_portal_drivers()["naukri"]
        page = _FakePage(
            "https://errors.edgesuite.net/18.example",
            visible_texts={"text=Access Denied"},
        )
        reason = driver._manual_reason_for_page(page, "https://www.naukri.com/job-listings-demo")
        self.assertEqual(reason, "captcha_or_access_denied")

    def test_classifies_linkedin_company_website_apply_as_external(self) -> None:
        driver = build_portal_drivers()["linkedin"]
        page = _FakePage(
            "https://www.linkedin.com/jobs/view/123",
            visible_texts={"a[aria-label*='Apply on company website']"},
        )
        reason = driver._manual_reason_for_page(page, "https://www.linkedin.com/jobs/view/123")
        self.assertEqual(reason, "external_apply")


class _FakeLocator:
    def __init__(self, visible: bool) -> None:
        self._visible = visible

    def count(self) -> int:
        return 1 if self._visible else 0

    @property
    def first(self) -> "_FakeLocator":
        return self

    def is_visible(self, timeout: int = 0) -> bool:
        return self._visible


class _FakePage:
    def __init__(self, url: str, *, visible_texts: set[str]) -> None:
        self.url = url
        self._visible_texts = visible_texts

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(selector in self._visible_texts)


if __name__ == "__main__":
    unittest.main()
