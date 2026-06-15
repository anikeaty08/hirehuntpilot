from __future__ import annotations

from hirehuntpilot.models import ApplicationStatus, JobRecord


class PolicyEngine:
    def __init__(self, *, exclude_companies: set[str] | None = None, exclude_keywords: set[str] | None = None) -> None:
        self.exclude_companies = {name.casefold() for name in (exclude_companies or set())}
        self.exclude_keywords = {term.casefold() for term in (exclude_keywords or set())}

    def qualify(self, job: JobRecord) -> tuple[bool, str]:
        if job.company.casefold() in self.exclude_companies:
            return False, "company excluded"
        haystack = " ".join([job.title, job.description, " ".join(job.skills)]).casefold()
        for term in self.exclude_keywords:
            if term and term in haystack:
                return False, f"matched excluded keyword: {term}"
        return True, "qualified"

    def next_after_qualification(self, qualified: bool) -> ApplicationStatus:
        if qualified:
            return ApplicationStatus.QUALIFIED
        return ApplicationStatus.REJECTED

    def can_commit_apply(self, status: ApplicationStatus, has_dry_run: bool) -> tuple[bool, str]:
        if status not in {ApplicationStatus.PREPARED, ApplicationStatus.READY_TO_APPLY, ApplicationStatus.DRY_RUN_ONLY}:
            return False, f"job not ready for apply: {status}"
        if not has_dry_run:
            return False, "successful dry run required before commit"
        return True, "ok"
