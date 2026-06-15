from __future__ import annotations

from pathlib import Path

from hirehuntpilot.config import app_home
from hirehuntpilot.browser.portals import InternshalaDriver, NaukriDriver
from hirehuntpilot.models import ApplicationStatus, ArtifactRecord, TaskRecord, TaskType


class ApplyAgent:
    def __init__(self) -> None:
        self.drivers = {
            "naukri": NaukriDriver(),
            "internshala": InternshalaDriver(),
        }

    def handles(self) -> set[TaskType]:
        return {TaskType.DRY_RUN_APPLICATION, TaskType.SUBMIT_APPLICATION}

    def process(self, task: TaskRecord, supervisor) -> None:
        job_id = task.payload["job_id"]
        job = supervisor.state.get_job(job_id)
        application = supervisor.state.get_application(job_id)
        if not job or not application:
            raise ValueError(f"missing state for {job_id}")
        driver = self.drivers.get(job.source)
        if not driver:
            application.status = ApplicationStatus.MANUAL_REQUIRED
            application.notes = f"unsupported portal: {job.source}"
        else:
            artifacts = {item.artifact_type: item.path for item in supervisor.state.list_artifacts(job_id)}
            if task.task_type is TaskType.DRY_RUN_APPLICATION:
                result = driver.dry_run(job, artifacts)
            else:
                has_dry_run = any(
                    artifact.artifact_type == "dry_run_receipt"
                    for artifact in supervisor.state.list_artifacts(job_id)
                )
                allowed, reason = supervisor.policies.can_commit_apply(application.status, has_dry_run)
                if not allowed:
                    raise ValueError(reason)
                result = driver.submit(job, artifacts)
            application.status = ApplicationStatus(result.status)
            application.notes = result.notes
            application.screenshot_path = result.screenshot_path
            if task.task_type is TaskType.DRY_RUN_APPLICATION and application.status is ApplicationStatus.DRY_RUN_ONLY:
                logs_dir = app_home() / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                safe_job_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in job_id)
                receipt = logs_dir / f"dry_run_{safe_job_id}.txt"
                receipt.write_text(result.notes, encoding="utf-8")
                supervisor.state.add_artifact(
                    ArtifactRecord(
                        job_id=job_id,
                        artifact_type="dry_run_receipt",
                        path=str(receipt),
                    )
                )
            if task.task_type is TaskType.SUBMIT_APPLICATION and result.screenshot_path:
                supervisor.state.add_artifact(
                    ArtifactRecord(
                        job_id=job_id,
                        artifact_type="application_receipt",
                        path=result.screenshot_path,
                    )
                )
        supervisor.state.upsert_application(application)
        supervisor.enqueue(TaskType.SYNC_TRACKING, {"job_id": job_id}, job_id=job_id)
