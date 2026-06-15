from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import getpass
from pathlib import Path

from hirehuntpilot.ai.adapter import AIAdapter
from hirehuntpilot.browser.session import BrowserSessionManager
from hirehuntpilot.compat import dump_data, make_app, make_console, make_table, option
from hirehuntpilot.config import ConfigManager
from hirehuntpilot.doctor import run_doctor
from hirehuntpilot.models import ApplicationStatus
from hirehuntpilot.models import TaskType
from hirehuntpilot.resume.updater import merge_resume_data
from hirehuntpilot.runtime import build_supervisor


app = make_app(help_text="HireHuntPilot multi-agent orchestrator")
console = make_console()

AI_PROVIDER_CHOICES: list[tuple[str, str]] = [
    ("none", "No AI provider"),
    ("openai", "OpenAI / ChatGPT via API key"),
    ("google", "Google Gemini API key"),
    ("groq", "Groq API key"),
    ("mistral", "Mistral API key"),
    ("local", "Local OpenAI-compatible server"),
]

AI_MODEL_PRESETS: dict[str, list[str]] = {
    "openai": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-4.1", "gpt-4.1-mini"],
    "google": [
        "gemini-3.5-flash",
        "gemini-3.1-pro",
        "gemini-3-flash",
        "gemini-3.1-flash-lite",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ],
    "groq": [
        "openai/gpt-oss-120b",
        "llama-3.3-70b-versatile",
        "deepseek-r1-distill-llama-70b",
        "qwen/qwen3-32b",
    ],
    "mistral": ["mistral-medium-2508", "mistral-small-2506", "codestral-2501", "pixtral-large-2411"],
    "local": ["gemma3:12b", "gemma3:4b", "llama3.1:8b", "qwen2.5:7b-instruct", "mistral:7b"],
}


@app.command()
def init() -> None:
    manager = ConfigManager()
    if manager.path.exists():
        config = manager.load()
        console.print(f"Using existing config: {manager.path}")
    else:
        config = manager.bootstrap_defaults()
    _interactive_ai_setup(manager)
    config = manager.load()
    console.print(f"Initialized config: {manager.path}")
    console.print(f"Runtime DB: {config.runtime.sqlite_path}")


@app.command("ai-setup")
def ai_setup() -> None:
    manager = ConfigManager()
    _interactive_ai_setup(manager)
    config = manager.load()
    console.print(f"AI provider saved: {config.ai.provider} / {config.ai.model}")


@app.command()
def doctor() -> None:
    table = make_table(title="HireHuntPilot Doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for result in run_doctor():
        table.add_row(result.name, "OK" if result.ok else "FAIL", result.detail)
    console.print(table)


@app.command()
def run(limit: int = option(25, help="Search result limit")) -> None:
    manager = ConfigManager()
    config = manager.load()
    supervisor = build_supervisor(config)
    supervisor.enqueue(
        TaskType.SEARCH_SOURCES,
        {
            "query": config.preferences.role or "python developer",
            "cities": config.preferences.cities,
            "sources": config.preferences.sources,
            "limit": limit,
        },
    )
    completed = supervisor.run_until_idle()
    qualified = sum(1 for item in supervisor.state.list_applications() if item.status is ApplicationStatus.QUALIFIED)
    supervisor.enqueue(
        TaskType.SEND_NOTIFICATION,
        {"message": f"Hunt complete at {datetime.now(timezone.utc).isoformat()}: qualified={qualified}, tasks={completed}"},
    )
    supervisor.run_until_idle()
    console.print(f"Run completed tasks={completed} qualified={qualified}")


@app.command()
def prepare() -> None:
    manager = ConfigManager()
    config = manager.load()
    supervisor = build_supervisor(config)
    for application in supervisor.state.list_applications():
        if application.status is ApplicationStatus.QUALIFIED:
            supervisor.enqueue(TaskType.PREPARE_APPLICATION, {"job_id": application.job_id}, job_id=application.job_id)
    completed = supervisor.run_until_idle()
    ready = sum(1 for item in supervisor.state.list_applications() if item.status is ApplicationStatus.READY_TO_APPLY)
    supervisor.enqueue(
        TaskType.SEND_NOTIFICATION,
        {"message": f"Preparation complete at {datetime.now(timezone.utc).isoformat()}: ready={ready}, tasks={completed}"},
    )
    supervisor.run_until_idle()
    console.print(f"Prepare completed tasks={completed} ready={ready}")


@app.command()
def apply(
    dry_run: bool = option(True, "--dry-run/--commit", help="Run dry-run instead of live submit"),
) -> None:
    manager = ConfigManager()
    config = manager.load()
    supervisor = build_supervisor(config)
    task_type = TaskType.DRY_RUN_APPLICATION if dry_run else TaskType.SUBMIT_APPLICATION
    eligible_statuses = {
        ApplicationStatus.READY_TO_APPLY,
        ApplicationStatus.PREPARED,
    } if dry_run else {ApplicationStatus.DRY_RUN_ONLY}
    for application in supervisor.state.list_applications():
        if application.status in eligible_statuses:
            supervisor.enqueue(task_type, {"job_id": application.job_id}, job_id=application.job_id)
    completed = supervisor.run_until_idle()
    target_status = ApplicationStatus.DRY_RUN_ONLY if dry_run else ApplicationStatus.APPLIED
    count = sum(1 for item in supervisor.state.list_applications() if item.status is target_status)
    supervisor.enqueue(
        TaskType.SEND_NOTIFICATION,
        {"message": f"Apply {'dry-run' if dry_run else 'commit'} complete at {datetime.now(timezone.utc).isoformat()}: count={count}, tasks={completed}"},
    )
    supervisor.run_until_idle()
    console.print(f"Apply completed tasks={completed} mode={'dry-run' if dry_run else 'commit'} count={count}")


@app.command()
def status() -> None:
    manager = ConfigManager()
    config = manager.load()
    supervisor = build_supervisor(config)
    counts = Counter(application.status for application in supervisor.state.list_applications())
    table = make_table(title="Application Status")
    table.add_column("Status")
    table.add_column("Count")
    for status_name, count in sorted(counts.items()):
        table.add_row(str(status_name), str(count))
    console.print(table)
    apps = supervisor.state.list_applications()[:5]
    if apps:
        recent = make_table(title="Recent Jobs")
        recent.add_column("Job")
        recent.add_column("Status")
        recent.add_column("Notes")
        for item in apps:
            recent.add_row(item.job_id, str(item.status), item.notes)
        console.print(recent)


@app.command("config-show")
def config_show() -> None:
    manager = ConfigManager()
    console.print(dump_data(manager.redacted_dict()))


@app.command("resume-update")
def resume_update(summary: str = option("", help="Update resume summary text")) -> None:
    manager = ConfigManager()
    config = manager.load()
    if summary:
        merged = merge_resume_data(config.resume.json_path, {"summary": summary})
        console.print(f"Updated resume summary keys={sorted(merged.keys())}")
    else:
        console.print(f"Resume JSON: {config.resume.json_path}")


@app.command("telegram-test")
def telegram_test() -> None:
    manager = ConfigManager()
    config = manager.load()
    supervisor = build_supervisor(config)
    supervisor.enqueue(TaskType.SEND_NOTIFICATION, {"message": "HireHuntPilot test notification"})
    supervisor.run_until_idle()
    console.print("Notification dispatch attempted.")


@app.command("telegram-relink")
def telegram_relink(
    bot_token: str = option("", help="Telegram bot token"),
    chat_id: str = option("", help="Telegram chat id"),
) -> None:
    manager = ConfigManager()
    manager.update("telegram", {"enabled": True, "bot_token": bot_token, "chat_id": chat_id})
    console.print("Telegram configuration updated.")


@app.command("telegram-disable")
def telegram_disable() -> None:
    manager = ConfigManager()
    manager.update("telegram", {"enabled": False, "bot_token": "", "chat_id": ""})
    console.print("Telegram notifications disabled.")


@app.command("sessions-refresh")
def sessions_refresh(headed: bool = option(False, help="Record headed preference in session stub")) -> None:
    manager = ConfigManager()
    config = manager.load()
    sessions = BrowserSessionManager()
    table = make_table(title="Session Refresh")
    table.add_column("Portal")
    table.add_column("Status")
    table.add_column("Detail")
    for portal in config.preferences.sources:
        credentials = config.portals.get(portal)
        email = credentials.email if credentials else ""
        ok, detail = sessions.refresh_session(portal, email=email, headed=headed)
        table.add_row(portal, "OK" if ok else "FAIL", detail)
    console.print(table)


def _interactive_ai_setup(manager: ConfigManager) -> None:
    config = manager.load()
    if not _confirm("Configure AI provider now?", default=True):
        return
    while True:
        provider = _select_provider(config.ai.provider)
        if provider == "none":
            manager.update("ai", {"provider": "none", "api_key": "", "model": "", "base_url": ""})
            console.print("AI provider set to fallback-only mode.")
            return
        suggested_model = config.ai.model if config.ai.provider == provider else ""
        model = _select_model(provider, suggested_model)
        api_key = _prompt_secret(f"{provider} API key", default=config.ai.api_key) if provider != "local" else ""
        base_url = _prompt_base_url(provider, config.ai.base_url if config.ai.provider == provider else "")
        manager.update(
            "ai",
            {
                "provider": provider,
                "api_key": api_key,
                "model": model,
                "base_url": base_url,
            },
        )
        ok, detail = AIAdapter(manager.load().ai).healthcheck()
        console.print(f"AI model check: {'OK' if ok else 'FAIL'} - {detail}")
        if provider == "openai":
            console.print("This uses the OpenAI API key path. ChatGPT web account auth is not used here.")
        if ok or not _confirm("Retry AI setup?", default=True):
            return


def _confirm(prompt: str, *, default: bool) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    raw = input(prompt + suffix).strip().casefold()
    if not raw:
        return default
    return raw in {"y", "yes"}


def _select_provider(current: str) -> str:
    console.print("Select AI provider:")
    for index, (_, label) in enumerate(AI_PROVIDER_CHOICES, start=1):
        console.print(f"{index}. {label}")
    default_index = next((idx for idx, (value, _) in enumerate(AI_PROVIDER_CHOICES, start=1) if value == current), 1)
    while True:
        raw = input(f"Provider choice [{default_index}]: ").strip()
        if not raw:
            return AI_PROVIDER_CHOICES[default_index - 1][0]
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(AI_PROVIDER_CHOICES):
                return AI_PROVIDER_CHOICES[idx - 1][0]
        console.print("Invalid selection.")


def _select_model(provider: str, current: str) -> str:
    presets = AI_MODEL_PRESETS.get(provider, [])
    console.print(f"Select model for {provider}:")
    if provider == "google":
        console.print("Gemini presets include current 3.x and 2.5 families, including lighter tiers for lower-cost use.")
    if provider == "groq":
        console.print("Groq presets focus on current hosted open and agentic-friendly models.")
        console.print("Recommended default for coding and resume tailoring: llama-3.3-70b-versatile.")
    if provider == "local":
        console.print("Local presets assume an OpenAI-compatible endpoint such as Ollama or LM Studio.")
    for index, model in enumerate(presets, start=1):
        console.print(f"{index}. {model}")
    custom_index = len(presets) + 1
    console.print(f"{custom_index}. Custom model")
    default_index = 1
    if current in presets:
        default_index = presets.index(current) + 1
    elif current:
        default_index = custom_index
    while True:
        raw = input(f"Model choice [{default_index}]: ").strip()
        if not raw:
            choice = default_index
        elif raw.isdigit():
            choice = int(raw)
        else:
            console.print("Invalid selection.")
            continue
        if 1 <= choice <= len(presets):
            return presets[choice - 1]
        if choice == custom_index:
            custom_default = current or ""
            custom = input(f"Custom model{f' [{custom_default}]' if custom_default else ''}: ").strip()
            return custom or custom_default
        console.print("Invalid selection.")


def _prompt_secret(label: str, *, default: str) -> str:
    hint = " [press Enter to keep existing]" if default else ""
    value = getpass.getpass(f"{label}{hint}: ").strip()
    return value or default


def _prompt_base_url(provider: str, current: str) -> str:
    defaults = {
        "openai": "",
        "google": "",
        "mistral": "https://api.mistral.ai",
        "local": "http://localhost:11434/v1",
        "groq": "",
        "anthropic": "",
    }
    suggested = current or defaults.get(provider, "")
    raw = input(f"Base URL [{suggested}]: ").strip()
    return raw or suggested


if __name__ == "__main__":
    app()
