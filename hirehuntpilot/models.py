from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


class ApplicationStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    READY_TO_PREPARE = "READY_TO_PREPARE"
    PREPARED = "PREPARED"
    READY_TO_APPLY = "READY_TO_APPLY"
    DRY_RUN_ONLY = "DRY_RUN_ONLY"
    APPLIED = "APPLIED"
    FAILED = "FAILED"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    SKIPPED = "SKIPPED"


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    RETRY = "RETRY"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class TaskType(StrEnum):
    SEARCH_SOURCES = "search_sources"
    QUALIFY_JOB = "qualify_job"
    PREPARE_APPLICATION = "prepare_application"
    DRY_RUN_APPLICATION = "dry_run_application"
    SUBMIT_APPLICATION = "submit_application"
    SYNC_TRACKING = "sync_tracking"
    SEND_NOTIFICATION = "send_notification"


@dataclass(slots=True)
class JobRecord:
    source_job_id: str
    title: str
    company: str
    source: str
    job_url: str
    apply_url: str | None = None
    location: str = ""
    city: str = ""
    country: str = "India"
    work_mode: str = "unknown"
    job_kind: str = "job"
    experience: str = ""
    salary: str = ""
    stipend: str = ""
    skills: list[str] = field(default_factory=list)
    description: str = ""
    easy_apply: bool = False
    match_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_job_id": self.source_job_id,
            "title": self.title,
            "company": self.company,
            "source": self.source,
            "job_url": self.job_url,
            "apply_url": self.apply_url,
            "location": self.location,
            "city": self.city,
            "country": self.country,
            "work_mode": self.work_mode,
            "job_kind": self.job_kind,
            "experience": self.experience,
            "salary": self.salary,
            "stipend": self.stipend,
            "skills": list(self.skills),
            "description": self.description,
            "easy_apply": self.easy_apply,
            "match_score": self.match_score,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobRecord":
        payload = dict(data)
        payload["skills"] = list(payload.get("skills", []))
        payload["metadata"] = dict(payload.get("metadata", {}))
        return cls(**payload)


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    task_type: TaskType
    payload: dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    job_id: str | None = None
    attempt: int = 0
    error: str | None = None
    scheduled_at: datetime = field(default_factory=utc_now)
    leased_until: datetime | None = None


@dataclass(slots=True)
class ArtifactRecord:
    job_id: str
    artifact_type: str
    path: str
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ApplicationRecord:
    job_id: str
    status: ApplicationStatus
    notes: str = ""
    discovered_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    resume_version: str | None = None
    screenshot_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
