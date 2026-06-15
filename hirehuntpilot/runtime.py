from __future__ import annotations

from hirehuntpilot.agents.apply import ApplyAgent
from hirehuntpilot.agents.gatekeeper import GatekeeperAgent
from hirehuntpilot.agents.notifier import NotificationAgent
from hirehuntpilot.agents.resume import ResumeAgent
from hirehuntpilot.agents.scout import ScoutAgent
from hirehuntpilot.agents.tracker import TrackerAgent
from hirehuntpilot.ai.adapter import AIAdapter
from hirehuntpilot.config import AppConfig
from hirehuntpilot.integrations.sheets import SheetsTracker
from hirehuntpilot.notifiers.service import NotificationService
from hirehuntpilot.orchestrator.bus import EventBus
from hirehuntpilot.orchestrator.policies import PolicyEngine
from hirehuntpilot.orchestrator.state import StateStore
from hirehuntpilot.orchestrator.supervisor import Supervisor, SupervisorContext


def build_supervisor(config: AppConfig) -> Supervisor:
    state = StateStore(config.runtime.sqlite_path)
    bus = EventBus(state)
    policies = PolicyEngine(
        exclude_companies=set(config.preferences.exclude_companies),
        exclude_keywords=set(config.preferences.exclude_keywords),
    )
    tracker = SheetsTracker(config.sheets.spreadsheet_id, config.sheets.service_account_json_path)
    notifications = NotificationService(config)
    context = SupervisorContext(config=config, state=state, bus=bus, policies=policies)
    agents = [
        ScoutAgent(),
        GatekeeperAgent(),
        ResumeAgent(AIAdapter(config.ai)),
        ApplyAgent(),
        TrackerAgent(tracker),
        NotificationAgent(notifications),
    ]
    return Supervisor(context, agents)
