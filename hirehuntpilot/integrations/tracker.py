from __future__ import annotations

import csv

from hirehuntpilot.config import app_home
from hirehuntpilot.models import ApplicationRecord, JobRecord


TRACKER_HEADERS = [
    "source_job_id",
    "title",
    "company",
    "source",
    "location",
    "work_mode",
    "job_kind",
    "experience",
    "salary",
    "stipend",
    "skills",
    "match_score",
    "easy_apply",
    "job_url",
    "apply_url",
    "status",
    "discovered_at",
    "applied_at",
    "resume_version",
    "screenshot_path",
    "notes",
]


class LocalTracker:
    def __init__(self) -> None:
        self.local_ledger_path = app_home() / "database" / "applications.csv"

    def check_connection(self) -> tuple[bool, str]:
        self.local_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        return True, f"local tracker active at {self.local_ledger_path}"

    def sync_application(self, job: JobRecord, application: ApplicationRecord) -> tuple[bool, str]:
        self.local_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, str]] = []
        if self.local_ledger_path.exists():
            with self.local_ledger_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
        row = {
            "source_job_id": job.source_job_id,
            "title": job.title,
            "company": job.company,
            "source": job.source,
            "location": job.location,
            "work_mode": job.work_mode,
            "job_kind": job.job_kind,
            "experience": job.experience,
            "salary": job.salary,
            "stipend": job.stipend,
            "skills": ", ".join(job.skills),
            "match_score": str(job.match_score),
            "easy_apply": str(job.easy_apply),
            "job_url": job.job_url,
            "apply_url": job.apply_url or "",
            "status": str(application.status),
            "discovered_at": application.discovered_at.isoformat(),
            "applied_at": application.updated_at.isoformat(),
            "resume_version": application.resume_version or "",
            "screenshot_path": application.screenshot_path or "",
            "notes": application.notes,
        }
        replaced = False
        for idx, existing in enumerate(rows):
            if existing.get("source_job_id") == job.source_job_id:
                rows[idx] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        with self.local_ledger_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=TRACKER_HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        return True, f"local ledger updated at {self.local_ledger_path}"
