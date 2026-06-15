from __future__ import annotations

from typing import Any

from hirehuntpilot.orchestrator.state import StateStore


class EventBus:
    def __init__(self, state: StateStore) -> None:
        self.state = state

    def publish(self, event_type: str, payload: dict[str, Any], job_id: str | None = None) -> None:
        self.state.emit_event(event_type=event_type, payload=payload, job_id=job_id)
