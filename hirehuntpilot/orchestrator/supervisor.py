from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from hirehuntpilot.config import AppConfig
from hirehuntpilot.models import TaskRecord, TaskType
from hirehuntpilot.orchestrator.bus import EventBus
from hirehuntpilot.orchestrator.policies import PolicyEngine
from hirehuntpilot.orchestrator.state import StateStore


class Agent(Protocol):
    def handles(self) -> set[TaskType]:
        ...

    def process(self, task: TaskRecord, supervisor: "Supervisor") -> None:
        ...


@dataclass(slots=True)
class SupervisorContext:
    config: AppConfig
    state: StateStore
    bus: EventBus
    policies: PolicyEngine


class Supervisor:
    def __init__(self, context: SupervisorContext, agents: list[Agent]) -> None:
        self.context = context
        self._agents = agents
        self._dispatch = {
            task_type: agent
            for agent in agents
            for task_type in agent.handles()
        }

    @property
    def config(self) -> AppConfig:
        return self.context.config

    @property
    def state(self) -> StateStore:
        return self.context.state

    @property
    def bus(self) -> EventBus:
        return self.context.bus

    @property
    def policies(self) -> PolicyEngine:
        return self.context.policies

    def enqueue(self, task_type: TaskType, payload: dict, *, job_id: str | None = None) -> None:
        self.state.enqueue_task(task_type, payload, job_id=job_id)

    def run_until_idle(self, *, max_iterations: int = 500) -> int:
        completed = 0
        for _ in range(max_iterations):
            task = self.state.lease_task()
            if not task:
                break
            agent = self._dispatch.get(task.task_type)
            if not agent:
                self.state.fail_task(task.task_id, f"no agent registered for {task.task_type}")
                continue
            try:
                agent.process(task, self)
            except Exception as exc:  # pragma: no cover - defensive control flow
                if task.attempt >= 2:
                    self.state.fail_task(task.task_id, str(exc))
                else:
                    self.state.retry_task(task, str(exc), delay_seconds=5 * (task.attempt + 1))
            else:
                self.state.complete_task(task.task_id)
                completed += 1
        return completed
