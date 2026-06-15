from __future__ import annotations

from hirehuntpilot.config import app_home
from hirehuntpilot.notifiers.service import NotificationService
from hirehuntpilot.models import TaskRecord, TaskType


class NotificationAgent:
    def __init__(self, service: NotificationService) -> None:
        self.service = service

    def handles(self) -> set[TaskType]:
        return {TaskType.SEND_NOTIFICATION}

    def process(self, task: TaskRecord, supervisor) -> None:
        log_dir = app_home() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        out = log_dir / "notifications.log"
        message = str(task.payload.get("message", task.payload))
        results = self.service.send(message)
        with out.open("a", encoding="utf-8") as handle:
            for result in results:
                handle.write(f"{result.channel}|{result.ok}|{result.detail}|{message}\n")
        supervisor.bus.publish(
            "notification_sent",
            {
                "message": message,
                "results": [
                    {"channel": result.channel, "ok": result.ok, "detail": result.detail}
                    for result in results
                ],
            },
            job_id=task.job_id,
        )
