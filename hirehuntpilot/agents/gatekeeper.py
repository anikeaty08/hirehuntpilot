from __future__ import annotations

from hirehuntpilot.models import ApplicationStatus, TaskRecord, TaskType


class GatekeeperAgent:
    def handles(self) -> set[TaskType]:
        return {TaskType.QUALIFY_JOB}

    def process(self, task: TaskRecord, supervisor) -> None:
        job_id = task.payload["job_id"]
        job = supervisor.state.get_job(job_id)
        if not job:
            raise ValueError(f"unknown job: {job_id}")
        qualified, reason = supervisor.policies.qualify(job)
        application = supervisor.state.get_application(job_id)
        if not application:
            raise ValueError(f"missing application record: {job_id}")
        application.status = ApplicationStatus.QUALIFIED if qualified else ApplicationStatus.REJECTED
        application.notes = reason
        supervisor.state.upsert_application(application)
        supervisor.bus.publish("job_qualified", {"qualified": qualified, "reason": reason}, job_id=job_id)
        supervisor.enqueue(TaskType.SYNC_TRACKING, {"job_id": job_id}, job_id=job_id)
