from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from hirehuntpilot.models import (
    ApplicationRecord,
    ApplicationStatus,
    ArtifactRecord,
    JobRecord,
    TaskRecord,
    TaskStatus,
    TaskType,
    utc_now,
)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class StateStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS applications (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resume_version TEXT,
                    screenshot_path TEXT,
                    extra TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    job_id TEXT,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    error TEXT,
                    scheduled_at TEXT NOT NULL,
                    leased_until TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    job_id TEXT,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS locks (
                    lock_key TEXT PRIMARY KEY,
                    leased_until TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_unique_pending
                ON tasks(task_type, COALESCE(job_id, ''), payload, status)
                WHERE status IN ('PENDING', 'RUNNING', 'RETRY');
                """
            )

    def store_job(self, job: JobRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO jobs(job_id, payload) VALUES(?, ?)",
                (job.source_job_id, json.dumps(job.to_dict())),
            )

    def get_job(self, job_id: str) -> JobRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if not row:
            return None
        return JobRecord.from_dict(json.loads(row["payload"]))

    def list_jobs(self) -> list[JobRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM jobs ORDER BY job_id").fetchall()
        return [JobRecord.from_dict(json.loads(row["payload"])) for row in rows]

    def upsert_application(self, record: ApplicationRecord) -> None:
        now = utc_now().isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO applications(job_id, status, notes, discovered_at, updated_at, resume_version, screenshot_path, extra)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status = excluded.status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at,
                    resume_version = excluded.resume_version,
                    screenshot_path = excluded.screenshot_path,
                    extra = excluded.extra
                """,
                (
                    record.job_id,
                    record.status,
                    record.notes,
                    record.discovered_at.isoformat(),
                    now,
                    record.resume_version,
                    record.screenshot_path,
                    json.dumps(record.extra),
                ),
            )

    def get_application(self, job_id: str) -> ApplicationRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM applications WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if not row:
            return None
        return ApplicationRecord(
            job_id=row["job_id"],
            status=ApplicationStatus(row["status"]),
            notes=row["notes"],
            discovered_at=_dt(row["discovered_at"]) or utc_now(),
            updated_at=_dt(row["updated_at"]) or utc_now(),
            resume_version=row["resume_version"],
            screenshot_path=row["screenshot_path"],
            extra=json.loads(row["extra"]),
        )

    def list_applications(self) -> list[ApplicationRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM applications ORDER BY updated_at DESC").fetchall()
        return [
            ApplicationRecord(
                job_id=row["job_id"],
                status=ApplicationStatus(row["status"]),
                notes=row["notes"],
                discovered_at=_dt(row["discovered_at"]) or utc_now(),
                updated_at=_dt(row["updated_at"]) or utc_now(),
                resume_version=row["resume_version"],
                screenshot_path=row["screenshot_path"],
                extra=json.loads(row["extra"]),
            )
            for row in rows
        ]

    def add_artifact(self, artifact: ArtifactRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts(job_id, artifact_type, path, created_at, metadata)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    artifact.job_id,
                    artifact.artifact_type,
                    artifact.path,
                    artifact.created_at.isoformat(),
                    json.dumps(artifact.metadata),
                ),
            )

    def list_artifacts(self, job_id: str) -> list[ArtifactRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE job_id = ? ORDER BY created_at",
                (job_id,),
            ).fetchall()
        return [
            ArtifactRecord(
                job_id=row["job_id"],
                artifact_type=row["artifact_type"],
                path=row["path"],
                created_at=_dt(row["created_at"]) or utc_now(),
                metadata=json.loads(row["metadata"]),
            )
            for row in rows
        ]

    def emit_event(self, event_type: str, payload: dict[str, Any], job_id: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO events(event_type, job_id, payload, created_at) VALUES(?, ?, ?, ?)",
                (event_type, job_id, json.dumps(payload), utc_now().isoformat()),
            )

    def enqueue_task(
        self,
        task_type: TaskType,
        payload: dict[str, Any],
        *,
        job_id: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> TaskRecord:
        record = TaskRecord(
            task_id=str(uuid.uuid4()),
            task_type=task_type,
            payload=payload,
            job_id=job_id,
            scheduled_at=scheduled_at or utc_now(),
        )
        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO tasks(task_id, task_type, job_id, payload, status, attempt, error, scheduled_at, leased_until)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.task_id,
                        record.task_type,
                        record.job_id,
                        json.dumps(record.payload, sort_keys=True),
                        record.status,
                        record.attempt,
                        record.error,
                        record.scheduled_at.isoformat(),
                        None,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE task_type = ? AND COALESCE(job_id, '') = COALESCE(?, '') AND payload = ?
                    AND status IN ('PENDING', 'RUNNING', 'RETRY')
                    ORDER BY scheduled_at
                    LIMIT 1
                    """,
                    (task_type, job_id, json.dumps(payload, sort_keys=True)),
                ).fetchone()
                if not existing:
                    raise
                return self._row_to_task(existing)
        return record

    def lease_task(self, lease_seconds: int = 60) -> TaskRecord | None:
        now = utc_now()
        lease_until = now + timedelta(seconds=lease_seconds)
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status IN ('PENDING', 'RETRY')
                AND scheduled_at <= ?
                ORDER BY scheduled_at, attempt
                LIMIT 1
                """,
                (now.isoformat(),),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """
                UPDATE tasks
                SET status = 'RUNNING', leased_until = ?
                WHERE task_id = ? AND status IN ('PENDING', 'RETRY')
                """,
                (lease_until.isoformat(), row["task_id"]),
            )
            updated = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (row["task_id"],)).fetchone()
        return self._row_to_task(updated)

    def complete_task(self, task_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = 'DONE', leased_until = NULL, error = NULL WHERE task_id = ?",
                (task_id,),
            )

    def retry_task(self, task: TaskRecord, error: str, delay_seconds: int = 30) -> None:
        scheduled_at = utc_now() + timedelta(seconds=delay_seconds)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'RETRY', error = ?, attempt = ?, leased_until = NULL, scheduled_at = ?
                WHERE task_id = ?
                """,
                (error, task.attempt + 1, scheduled_at.isoformat(), task.task_id),
            )

    def fail_task(self, task_id: str, error: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = 'FAILED', error = ?, leased_until = NULL WHERE task_id = ?",
                (error, task_id),
            )

    def list_tasks(self, status: TaskStatus | None = None) -> list[TaskRecord]:
        query = "SELECT * FROM tasks"
        params: tuple[Any, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY scheduled_at, attempt"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_task(row) for row in rows]

    def acquire_lock(self, lock_key: str, lease_seconds: int = 120) -> bool:
        expires = utc_now() + timedelta(seconds=lease_seconds)
        with self.connect() as conn:
            row = conn.execute("SELECT leased_until FROM locks WHERE lock_key = ?", (lock_key,)).fetchone()
            if row and (_dt(row["leased_until"]) or utc_now()) > utc_now():
                return False
            conn.execute(
                """
                INSERT INTO locks(lock_key, leased_until) VALUES(?, ?)
                ON CONFLICT(lock_key) DO UPDATE SET leased_until = excluded.leased_until
                """,
                (lock_key, expires.isoformat()),
            )
        return True

    def release_lock(self, lock_key: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM locks WHERE lock_key = ?", (lock_key,))

    def _row_to_task(self, row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            task_type=TaskType(row["task_type"]),
            payload=json.loads(row["payload"]),
            status=TaskStatus(row["status"]),
            job_id=row["job_id"],
            attempt=row["attempt"],
            error=row["error"],
            scheduled_at=_dt(row["scheduled_at"]) or utc_now(),
            leased_until=_dt(row["leased_until"]),
        )
