from __future__ import annotations

import csv
from pathlib import Path

from hirehuntpilot.config import app_home
from hirehuntpilot.models import ApplicationRecord, JobRecord


SHEET_HEADERS = [
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


class SheetsTracker:
    def __init__(self, spreadsheet_id: str, service_account_json_path: str) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.service_account_json_path = service_account_json_path
        self.local_ledger_path = app_home() / "applications.csv"

    def enabled(self) -> bool:
        return bool(self.spreadsheet_id and self.service_account_json_path)

    def check_connection(self) -> tuple[bool, str]:
        if not self.enabled():
            return False, "google sheets not configured"
        try:
            worksheet = self._worksheet()
            worksheet.row_values(1)
        except Exception as exc:  # pragma: no cover - depends on external service
            return False, str(exc)
        return True, "ok"

    def sync_application(self, job: JobRecord, application: ApplicationRecord) -> tuple[bool, str]:
        if not self.enabled():
            self._sync_local_ledger(job, application)
            return True, f"local ledger updated at {self.local_ledger_path}"
        worksheet = self._worksheet()
        rows = worksheet.get_all_records()
        row_index = None
        for idx, row in enumerate(rows, start=2):
            if row.get("source_job_id") == job.source_job_id:
                row_index = idx
                break

        payload = [
            job.source_job_id,
            job.title,
            job.company,
            job.source,
            job.location,
            job.work_mode,
            job.job_kind,
            job.experience,
            job.salary,
            job.stipend,
            ", ".join(job.skills),
            job.match_score,
            str(job.easy_apply),
            job.job_url,
            job.apply_url or "",
            application.status,
            application.discovered_at.isoformat(),
            application.updated_at.isoformat(),
            application.resume_version or "",
            application.screenshot_path or "",
            application.notes,
        ]
        if row_index is None:
            if not worksheet.row_values(1):
                worksheet.append_row(SHEET_HEADERS)
            worksheet.append_row(payload)
        else:
            worksheet.update(f"A{row_index}:U{row_index}", [payload])
        return True, "ok"

    def _sync_local_ledger(self, job: JobRecord, application: ApplicationRecord) -> None:
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
            writer = csv.DictWriter(handle, fieldnames=SHEET_HEADERS)
            writer.writeheader()
            writer.writerows(rows)

    def _worksheet(self):  # pragma: no cover - depends on external service
        import gspread

        client = gspread.service_account(filename=self.service_account_json_path)
        sheet = client.open_by_key(self.spreadsheet_id)
        return sheet.sheet1
