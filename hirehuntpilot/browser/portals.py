from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hirehuntpilot.config import app_home
from hirehuntpilot.models import JobRecord


@dataclass(slots=True)
class ApplyResult:
    status: str
    notes: str
    screenshot_path: str | None = None


class BasePortalDriver:
    portal_name = "base"

    def dry_run(self, job: JobRecord, artifacts: dict[str, str]) -> ApplyResult:
        if not (job.apply_url or job.job_url):
            return ApplyResult(status="MANUAL_REQUIRED", notes="no application target available")
        shot = self._write_screenshot(job, mode="dry-run")
        return ApplyResult(status="DRY_RUN_ONLY", notes=f"dry run captured for {self.portal_name}", screenshot_path=str(shot))

    def submit(self, job: JobRecord, artifacts: dict[str, str]) -> ApplyResult:
        if not (job.apply_url or job.job_url):
            return ApplyResult(status="MANUAL_REQUIRED", notes=f"no application target for {self.portal_name}")
        shot = self._write_screenshot(job, mode="submit")
        return ApplyResult(status="APPLIED", notes=f"simulated submit completed for {self.portal_name}", screenshot_path=str(shot))

    def _write_screenshot(self, job: JobRecord, *, mode: str) -> Path:
        root = app_home() / "screenshots"
        root.mkdir(parents=True, exist_ok=True)
        safe_job_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in job.source_job_id)
        path = root / f"{mode}_{job.source}_{safe_job_id}.txt"
        path.write_text(f"{mode} receipt for {job.title} @ {job.company}\n{job.apply_url or job.job_url}\n", encoding="utf-8")
        return path


class NaukriDriver(BasePortalDriver):
    portal_name = "naukri"


class InternshalaDriver(BasePortalDriver):
    portal_name = "internshala"
