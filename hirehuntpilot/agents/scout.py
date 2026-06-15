from __future__ import annotations

from hirehuntpilot.integrations.hirehunt_client import HireHuntClient
from hirehuntpilot.models import ApplicationRecord, ApplicationStatus, TaskRecord, TaskType


class ScoutAgent:
    def __init__(self, client: HireHuntClient | None = None) -> None:
        self.client = client or HireHuntClient()

    def handles(self) -> set[TaskType]:
        return {TaskType.SEARCH_SOURCES}

    def process(self, task: TaskRecord, supervisor) -> None:
        query = task.payload["query"]
        cities = task.payload.get("cities", [])
        sources = task.payload.get("sources", [])
        limit = int(task.payload.get("limit", 25))
        jobs = self.client.search(query=query, cities=cities, sources=sources, limit=limit)
        for job in jobs:
            supervisor.state.store_job(job)
            supervisor.state.upsert_application(
                ApplicationRecord(
                    job_id=job.source_job_id,
                    status=ApplicationStatus.DISCOVERED,
                )
            )
            supervisor.enqueue(TaskType.QUALIFY_JOB, {"job_id": job.source_job_id}, job_id=job.source_job_id)
        supervisor.bus.publish("search_completed", {"count": len(jobs), "query": query})
