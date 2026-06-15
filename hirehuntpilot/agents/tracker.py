from __future__ import annotations

from hirehuntpilot.integrations.sheets import SheetsTracker
from hirehuntpilot.models import TaskRecord, TaskType


class TrackerAgent:
    def __init__(self, tracker: SheetsTracker) -> None:
        self.tracker = tracker

    def handles(self) -> set[TaskType]:
        return {TaskType.SYNC_TRACKING}

    def process(self, task: TaskRecord, supervisor) -> None:
        job_id = task.payload["job_id"]
        job = supervisor.state.get_job(job_id)
        application = supervisor.state.get_application(job_id)
        if not job or not application:
            raise ValueError(f"missing state for {job_id}")
        ok, message = self.tracker.sync_application(job, application)
        supervisor.bus.publish("tracking_synced", {"ok": ok, "message": message}, job_id=job_id)
