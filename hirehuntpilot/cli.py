from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import sys

from hirehuntpilot.ai.adapter import AIAdapter
from hirehuntpilot.browser.session import BrowserSessionManager
from hirehuntpilot.compat import dump_data, make_app, make_console, make_table, option
from hirehuntpilot.config import ConfigManager
from hirehuntpilot.doctor import run_doctor
from hirehuntpilot.models import ApplicationRecord
from hirehuntpilot.models import ApplicationStatus
from hirehuntpilot.models import JobRecord
from hirehuntpilot.models import TaskType
from hirehuntpilot.orchestrator.state import StateStore
from hirehuntpilot.notifiers.service import NotificationService
from hirehuntpilot.portals import PORTAL_DEFINITIONS, available_portals
from hirehuntpilot.resume.updater import merge_resume_data
from hirehuntpilot.runtime import build_supervisor
from hirehuntpilot.setup import evaluate_setup, ready_for_prepare, ready_for_run


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
    _run_init_setup(manager)
    config = manager.load()
    console.print(f"Initialized config: {manager.path}")
    console.print(f"Runtime DB: {config.runtime.sqlite_path}")
    chat()


@app.command()
def setup() -> None:
    manager = ConfigManager()
    _run_init_setup(manager)


@app.command("setup-status")
def setup_status() -> None:
    manager = ConfigManager()
    config = manager.load()
    table = make_table(title="Setup Status")
    table.add_column("Step")
    table.add_column("Status")
    table.add_column("Detail")
    for label, state in [
        ("profile", config.setup.profile),
        ("resume", config.setup.resume),
        ("ai", config.setup.ai),
        ("notifications", config.setup.notifications),
    ]:
        table.add_row(label, state.status, state.detail)
    for portal in available_portals():
        state = config.setup.portals.get(portal)
        if state:
            table.add_row(f"portal.{portal}", state.status, state.detail)
    for check in evaluate_setup(config):
        table.add_row(f"check:{check.key}", "OK" if check.ok else "FAIL", check.detail)
    console.print(table)


def setup_profile() -> None:
    _setup_profile(ConfigManager())


def setup_resume() -> None:
    _setup_resume(ConfigManager())


@app.command("setup-ai")
def ai_setup() -> None:
    _interactive_ai_setup(ConfigManager())


def setup_notifications() -> None:
    _setup_notifications(ConfigManager())


@app.command("setup-portals")
def setup_portals() -> None:
    _setup_portals(ConfigManager())


def chat() -> None:
    _chat_loop(ConfigManager())


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
def run(prompt: str = option("", "--prompt", help="Initial request for the agent shell")) -> None:
    _chat_loop(ConfigManager(), initial_message=prompt.strip() or None)


def _run_search_command(limit: int = 25) -> None:
    manager = ConfigManager()
    config = manager.load()
    ready, issues = ready_for_run(config)
    if not ready:
        console.print("Run blocked. Complete setup first:")
        for issue in issues:
            console.print(f"- {issue}")
        return
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
    ready, issues = ready_for_prepare(config)
    if not ready:
        console.print("Prepare blocked. Complete setup first:")
        for issue in issues:
            console.print(f"- {issue}")
        return
    state = StateStore(config.runtime.sqlite_path)
    job_ids = [application.job_id for application in state.list_applications() if application.status is ApplicationStatus.QUALIFIED]
    completed = _prepare_jobs_for_ids(config, job_ids)
    supervisor = build_supervisor(config)
    ready = sum(1 for item in supervisor.state.list_applications() if item.status is ApplicationStatus.READY_TO_APPLY)
    _notify_pipeline(supervisor, f"Preparation complete at {datetime.now(timezone.utc).isoformat()}: ready={ready}, tasks={completed}")
    console.print(f"Prepare completed tasks={completed} ready={ready}")


@app.command()
def apply(
    dry_run: bool = option(True, "--dry-run/--commit", help="Run dry-run instead of live submit"),
) -> None:
    manager = ConfigManager()
    config = manager.load()
    state = StateStore(config.runtime.sqlite_path)
    eligible_statuses = {
        ApplicationStatus.READY_TO_APPLY,
        ApplicationStatus.PREPARED,
    } if dry_run else {
        ApplicationStatus.READY_TO_APPLY,
        ApplicationStatus.PREPARED,
        ApplicationStatus.DRY_RUN_ONLY,
    }
    job_ids = [application.job_id for application in state.list_applications() if application.status in eligible_statuses]
    completed = _apply_jobs_for_ids(config, job_ids, commit=not dry_run)
    target_status = ApplicationStatus.DRY_RUN_ONLY if dry_run else ApplicationStatus.APPLIED
    supervisor = build_supervisor(config)
    count = sum(1 for item in supervisor.state.list_applications() if item.status is target_status)
    _notify_pipeline(
        supervisor,
        f"Apply {'dry-run' if dry_run else 'commit'} complete at {datetime.now(timezone.utc).isoformat()}: count={count}, tasks={completed}",
    )
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


def resume_update(summary: str = option("", help="Update resume summary text")) -> None:
    manager = ConfigManager()
    config = manager.load()
    if summary:
        merged = merge_resume_data(config.resume.json_path, {"summary": summary})
        console.print(f"Updated resume summary keys={sorted(merged.keys())}")
    else:
        console.print(f"Resume JSON: {config.resume.json_path}")


def telegram_test() -> None:
    manager = ConfigManager()
    config = manager.load()
    supervisor = build_supervisor(config)
    supervisor.enqueue(TaskType.SEND_NOTIFICATION, {"message": "HireHuntPilot test notification"})
    supervisor.run_until_idle()
    console.print("Notification dispatch attempted.")


def telegram_relink(
    bot_token: str = option("", help="Telegram bot token"),
    chat_id: str = option("", help="Telegram chat id"),
) -> None:
    manager = ConfigManager()
    manager.update("telegram", {"enabled": True, "bot_token": bot_token, "chat_id": chat_id})
    console.print("Telegram configuration updated.")


def telegram_disable() -> None:
    manager = ConfigManager()
    manager.update("telegram", {"enabled": False, "bot_token": "", "chat_id": ""})
    console.print("Telegram notifications disabled.")


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
        ok, detail = sessions.refresh_session(portal, email=email, headed=headed, interactive=headed)
        table.add_row(portal, "OK" if ok else "FAIL", detail)
    console.print(table)


def _notify_pipeline(supervisor, message: str) -> None:
    supervisor.enqueue(TaskType.SEND_NOTIFICATION, {"message": message})
    supervisor.run_until_idle()


def _state_records(config) -> list[tuple[ApplicationRecord, JobRecord]]:
    state = StateStore(config.runtime.sqlite_path)
    rows: list[tuple[ApplicationRecord, JobRecord]] = []
    for application in state.list_applications():
        job = state.get_job(application.job_id)
        if job:
            rows.append((application, job))
    return rows


def _job_priority(application: ApplicationRecord, job: JobRecord) -> tuple[float, str]:
    priority = float(getattr(job, "match_score", 0.0) or 0.0)
    return (priority, application.updated_at.isoformat())


def _parallel_workers(count: int, *, max_workers: int) -> int:
    return max(1, min(count or 1, max_workers))


def _prepare_job(config, job_id: str) -> str:
    supervisor = build_supervisor(config)
    supervisor.enqueue(TaskType.PREPARE_APPLICATION, {"job_id": job_id}, job_id=job_id)
    supervisor.run_until_idle(max_iterations=50)
    application = supervisor.state.get_application(job_id)
    return str(application.status) if application else "MISSING"


def _apply_job(config, job_id: str, *, commit: bool) -> str:
    supervisor = build_supervisor(config)
    application = supervisor.state.get_application(job_id)
    if not application:
        return "MISSING"
    if application.status in {ApplicationStatus.QUALIFIED, ApplicationStatus.DISCOVERED}:
        supervisor.enqueue(TaskType.PREPARE_APPLICATION, {"job_id": job_id}, job_id=job_id)
        supervisor.run_until_idle(max_iterations=50)
        application = supervisor.state.get_application(job_id)
        if not application:
            return "MISSING"
    if application.status in {ApplicationStatus.READY_TO_APPLY, ApplicationStatus.PREPARED}:
        supervisor.enqueue(TaskType.DRY_RUN_APPLICATION, {"job_id": job_id}, job_id=job_id)
        supervisor.run_until_idle(max_iterations=50)
        application = supervisor.state.get_application(job_id)
        if not application:
            return "MISSING"
    if commit and application.status is ApplicationStatus.DRY_RUN_ONLY:
        supervisor.enqueue(TaskType.SUBMIT_APPLICATION, {"job_id": job_id}, job_id=job_id)
        supervisor.run_until_idle(max_iterations=50)
        application = supervisor.state.get_application(job_id)
        if not application:
            return "MISSING"
    return str(application.status)


def _prepare_jobs_for_ids(config, job_ids: list[str]) -> int:
    if not job_ids:
        return 0
    completed = 0
    workers = _parallel_workers(len(job_ids), max_workers=8)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_prepare_job, config, job_id): job_id for job_id in job_ids}
        for future in as_completed(futures):
            future.result()
            completed += 1
    return completed


def _apply_jobs_for_ids(config, job_ids: list[str], *, commit: bool) -> int:
    if not job_ids:
        return 0
    completed = 0
    workers = _parallel_workers(len(job_ids), max_workers=6 if commit else 8)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_apply_job, config, job_id, commit=commit): job_id for job_id in job_ids}
        for future in as_completed(futures):
            future.result()
            completed += 1
    return completed


def _run_search_pipeline(config, *, role: str, city: str, sources: list[str], limit: int) -> tuple[int, int]:
    supervisor = build_supervisor(config)
    supervisor.enqueue(
        TaskType.SEARCH_SOURCES,
        {
            "query": role or config.preferences.role or "python developer",
            "cities": [city] if city else config.preferences.cities,
            "sources": sources,
            "limit": limit,
        },
    )
    completed = supervisor.run_until_idle()
    qualified = sum(1 for item in supervisor.state.list_applications() if item.status is ApplicationStatus.QUALIFIED)
    _notify_pipeline(
        supervisor,
        f"Hunt complete at {datetime.now(timezone.utc).isoformat()}: qualified={qualified}, tasks={completed}",
    )
    return completed, qualified


def _application_status(config, job_id: str) -> ApplicationStatus | None:
    state = StateStore(config.runtime.sqlite_path)
    application = state.get_application(job_id)
    return application.status if application else None


def _select_jobs_for_apply(config, *, target_count: int, sources: list[str]) -> list[str]:
    rows = []
    for application, job in _state_records(config):
        if job.source not in sources:
            continue
        if application.status not in {ApplicationStatus.QUALIFIED, ApplicationStatus.READY_TO_APPLY, ApplicationStatus.PREPARED}:
            continue
        rows.append((application, job))
    rows.sort(key=lambda item: _job_priority(item[0], item[1]), reverse=True)
    return [application.job_id for application, _ in rows[:target_count]]


def _run_setup(
    manager: ConfigManager,
    *,
    include_profile: bool,
    include_resume: bool,
    include_ai: bool,
    include_notifications: bool,
    include_portals: bool,
) -> None:
    if include_profile:
        _setup_profile(manager)
    if include_resume:
        _setup_resume(manager)
    if include_ai:
        _interactive_ai_setup(manager)
    if include_notifications:
        _setup_notifications(manager)
    if include_portals:
        _setup_portals(manager)


def _run_init_setup(manager: ConfigManager) -> None:
    _interactive_ai_setup(manager)
    _setup_resume_from_root(manager)
    _setup_notifications(manager)
    _setup_portals(manager)


def _setup_profile(manager: ConfigManager) -> None:
    config = manager.load()
    if not _confirm("Configure profile info now?", default=True):
        manager.set_setup_step("profile", status="skipped", detail="profile setup skipped")
        return
    payload = {
        "name": _prompt_text("Full name", config.personal.name),
        "email": _prompt_text("Email", config.personal.email),
        "phone": _prompt_text("Phone", config.personal.phone),
        "linkedin": _prompt_text("LinkedIn URL", config.personal.linkedin),
        "github": _prompt_text("GitHub URL", config.personal.github),
        "portfolio": _prompt_text("Portfolio URL", config.personal.portfolio),
    }
    manager.update("personal", payload)
    manager.set_setup_step("profile", status="complete", detail="profile saved")


def _setup_resume(manager: ConfigManager) -> None:
    config = manager.load()
    if not _confirm("Configure resume profile now?", default=True):
        manager.set_setup_step("resume", status="skipped", detail="resume setup skipped")
        return
    resume_path = Path(config.resume.json_path or Path(config_manager_path(manager)).with_name("resume.json"))
    source_path = _find_resume_source()
    if source_path and _confirm(f"Use root resume source file {source_path.name}?", default=True):
        payload = _ingest_resume_source(manager, source_path)
        resume_path.parent.mkdir(parents=True, exist_ok=True)
        resume_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        manager.update("resume", {"json_path": str(resume_path)})
        manager.set_setup_step("resume", status="complete", detail=f"{resume_path} <- {source_path.name}")
        return
    current: dict[str, object] = {}
    if resume_path.exists():
        try:
            current = json.loads(resume_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    payload: dict[str, object] = {
        "name": _prompt_text("Resume name", str(current.get("name", config.personal.name))),
        "headline": _prompt_text("Headline", str(current.get("headline", ""))),
        "summary": _prompt_text("Summary", str(current.get("summary", ""))),
        "skills": _prompt_list("Skills (comma separated)", current.get("skills")),
        "experience": _prompt_entries("Experience entries", current.get("experience"), ["company", "position", "summary"]),
        "projects": _prompt_entries("Project entries", current.get("projects"), ["name", "summary"]),
        "education": _prompt_entries("Education entries", current.get("education"), ["institution", "area", "degree", "summary"]),
    }
    if config.ai.provider not in {"", "none"} and _confirm("Use configured LLM to normalize spelling and resume wording?", default=True):
        payload = AIAdapter(manager.load().ai).normalize_resume_profile(payload)
    resume_path.parent.mkdir(parents=True, exist_ok=True)
    resume_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manager.update("resume", {"json_path": str(resume_path)})
    manager.set_setup_step("resume", status="complete", detail=str(resume_path))


def _setup_resume_from_root(manager: ConfigManager) -> None:
    config = manager.load()
    source_path = _find_resume_source()
    if not source_path:
        manager.set_setup_step("resume", status="pending", detail="no root resume source found")
        console.print("No root resume source found. Add resume.txt, resume.md, or resume.json to continue.")
        return
    payload = _ingest_resume_source(manager, source_path)
    resume_path = Path(config.resume.json_path or Path(config_manager_path(manager)).with_name("resume.json"))
    resume_path.parent.mkdir(parents=True, exist_ok=True)
    resume_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manager.update("resume", {"json_path": str(resume_path)})
    manager.set_setup_step("resume", status="complete", detail=f"{resume_path} <- {source_path.name}")
    console.print(f"Resume source ingested from {source_path.name}")


def _interactive_ai_setup(manager: ConfigManager) -> None:
    if not _confirm("Configure AI provider now?", default=True):
        manager.set_setup_step("ai", status="skipped", detail="ai setup skipped")
        return
    while True:
        config = manager.load()
        provider = _select_provider(config.ai.provider)
        if provider == "none":
            manager.update("ai", {"provider": "none", "api_key": "", "model": "", "base_url": ""})
            console.print("AI provider set to fallback-only mode.")
            manager.set_setup_step("ai", status="skipped", detail="fallback-only mode")
            return
        api_key = _prompt_secret(f"{provider} API key", default=config.ai.api_key) if provider != "local" else ""
        base_url = _prompt_base_url(provider, config.ai.base_url if config.ai.provider == provider else "")
        suggested_model = config.ai.model if config.ai.provider == provider else ""
        model = _select_model(provider, suggested_model)
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
        manager.set_setup_step("ai", status="complete" if ok else "pending", detail=detail)
        if ok or not _confirm("Retry AI setup?", default=True):
            return


def _setup_notifications(manager: ConfigManager) -> None:
    config = manager.load()
    if not _confirm("Configure notifications now?", default=True):
        manager.set_setup_step("notifications", status="skipped", detail="notifications skipped")
        return
    enable_telegram = _confirm("Enable Telegram notifications?", default=config.telegram.enabled)
    telegram_payload = {
        "enabled": enable_telegram,
        "bot_token": config.telegram.bot_token,
        "chat_id": config.telegram.chat_id,
    }
    if enable_telegram:
        telegram_payload["bot_token"] = _prompt_secret("Telegram bot token", default=config.telegram.bot_token)
        telegram_payload["chat_id"] = _prompt_text("Telegram chat id", config.telegram.chat_id)
    else:
        telegram_payload["bot_token"] = ""
        telegram_payload["chat_id"] = ""
    manager.update("telegram", telegram_payload)
    results = NotificationService(manager.load()).send("HireHuntPilot setup test notification")
    detail = "; ".join(f"{result.channel}:{result.detail}" for result in results)
    manager.set_setup_step("notifications", status="complete", detail=detail)
    console.print(f"Notification setup: {detail}")


def _setup_portals(manager: ConfigManager) -> None:
    config = manager.load()
    sessions = BrowserSessionManager()
    valid_sessions = {portal for portal in available_portals() if sessions.portal_session_valid(portal)[0]}
    chosen_portals = _select_portals_for_setup(sorted(valid_sessions) or config.preferences.sources)
    enabled_sources: list[str] = []
    configured: list[str] = []
    console.print("")
    for portal in available_portals():
        portal_label = PORTAL_DEFINITIONS[portal].label
        if portal not in chosen_portals:
            manager.set_setup_step(f"portals.{portal}", status="skipped", detail="portal setup skipped")
            continue
        existing_ok, existing_detail = sessions.portal_session_valid(portal)
        console.print("─" * 28)
        console.print(portal_label)
        console.print("─" * 28)
        if existing_ok:
            ok, detail = True, existing_detail
            console.print("Existing valid session found.")
        else:
            ok, detail = sessions.refresh_session(portal, headed=True, interactive=True)
        if ok:
            enabled_sources.append(portal)
            configured.append(portal_label)
        manager.set_setup_step(f"portals.{portal}", status="complete" if ok else "pending", detail=detail)
        console.print(f"{'✓' if ok else 'x'} {portal_label} session {'saved' if ok else 'not saved'}")
        if not ok:
            console.print(detail)
        console.print("")
    manager.update("preferences", {"sources": enabled_sources})
    console.print("─" * 28)
    console.print("Setup complete")
    console.print("")
    console.print("Configured portals:")
    for label in configured:
        console.print(f"✓ {label}")
    if not configured:
        console.print("No portal sessions were saved.")
    console.print("")
    console.print(f"Sessions saved: {os.path.expanduser(str(sessions.sessions_root))}")


def _chat_loop(manager: ConfigManager, *, initial_message: str | None = None) -> None:
    config = manager.load()
    ai_ok, ai_detail = AIAdapter(config.ai).healthcheck()
    if config.ai.provider in {"", "none"}:
        console.print("[bold red]LLM is not integrated.[/bold red] Run `hirehuntpilot setup-ai` in another shell.")
    elif not ai_ok:
        console.print(f"[bold red]LLM is not integrated.[/bold red] {ai_detail}")
    if not config.preferences.sources:
        console.print("[bold red]No job portals are enabled.[/bold red] Run `hirehuntpilot setup-portals`.")
    console.print("HirePilot agent mode. Describe the jobs you want, or type /help. Type /exit to leave.")
    pending_action: dict[str, object] | None = None
    while True:
        if initial_message is not None:
            message = initial_message.strip()
            initial_message = None
        else:
            try:
                message = input("hirepilot> ").strip()
            except EOFError:
                console.print("")
                return
        if not message:
            continue
        if message in {"/exit", "exit", "quit"}:
            return
        if message == "/help":
            console.print(
                "Commands: /ingest-resume, /prepare, /apply dry-run, /apply commit, /status, /doctor, /verify, /config, /exit"
            )
            continue
        if message == "/ingest-resume":
            source_path = _find_resume_source()
            if not source_path:
                console.print("No root resume source found. Add resume.txt, resume.md, or resume.json to the repo root.")
                continue
            payload = _ingest_resume_source(manager, source_path)
            config = manager.load()
            resume_path = Path(config.resume.json_path)
            resume_path.parent.mkdir(parents=True, exist_ok=True)
            resume_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            manager.update("resume", {"json_path": str(resume_path)})
            manager.set_setup_step("resume", status="complete", detail=f"{resume_path} <- {source_path.name}")
            console.print(f"Canonical resume saved: {resume_path}")
            continue
        if message == "/prepare":
            prepare()
            continue
        if message == "/apply dry-run":
            apply(dry_run=True)
            continue
        if message == "/apply commit":
            apply(dry_run=False)
            continue
        if message == "/status":
            status()
            continue
        if message == "/doctor":
            doctor()
            continue
        if message == "/verify":
            _chat_verify(manager)
            continue
        if message == "/config":
            config_show()
            continue
        if pending_action:
            pending_action = _chat_continue_action(manager, pending_action, message)
            continue
        pending_action = _chat_dispatch_natural(manager, message)
        if pending_action:
            if pending_action.get("_handled"):
                pending_action = None
            continue
        _chat_answer(manager, message)


def _chat_verify(manager: ConfigManager) -> None:
    config = manager.load()
    ready_run, run_issues = ready_for_run(config)
    ready_prepare, prepare_issues = ready_for_prepare(config)
    table = make_table(title="Readiness")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    table.add_row("run", "OK" if ready_run else "FAIL", ", ".join(run_issues) if run_issues else "ready")
    table.add_row("prepare", "OK" if ready_prepare else "FAIL", ", ".join(prepare_issues) if prepare_issues else "ready")
    console.print(table)


def _chat_answer(manager: ConfigManager, message: str) -> None:
    config = manager.load()
    supervisor = build_supervisor(config)
    apps = supervisor.state.list_applications()[:5]
    context_lines = [
        f"role={config.preferences.role}",
        f"cities={','.join(config.preferences.cities)}",
        f"sources={','.join(config.preferences.sources)}",
        f"resume_json={config.resume.json_path}",
        f"recent_applications={len(apps)}",
    ]
    for app_item in apps:
        context_lines.append(f"{app_item.job_id}:{app_item.status}:{app_item.notes}")
    answer = AIAdapter(config.ai).chat_response(message, context="\n".join(context_lines))
    console.print(answer)


def _chat_dispatch_natural(manager: ConfigManager, message: str) -> dict[str, object] | None:
    config = manager.load()
    context = (
        f"default_role={config.preferences.role}\n"
        f"default_cities={','.join(config.preferences.cities)}\n"
        f"sources={','.join(config.preferences.sources)}"
    )
    action = AIAdapter(config.ai).plan_chat_action(message, context=context)
    intent = str(action.get("intent", "chat"))
    missing = [str(item) for item in action.get("missing", []) if item]
    if intent == "chat":
        return None
    if intent in {"search", "search_apply"}:
        if not action.get("role"):
            action["role"] = config.preferences.role
        if not action.get("city") and config.preferences.cities:
            action["city"] = config.preferences.cities[0]
        missing = [field for field in ("role", "city") if not action.get(field)]
        if missing:
            action["missing"] = missing
            _prompt_for_missing_field(missing[0])
            return action
        _execute_search_like_action(manager, action)
        return {"_handled": True}
    if intent == "prepare":
        prepare()
        return {"_handled": True}
    if intent == "apply":
        config = manager.load()
        state = StateStore(config.runtime.sqlite_path)
        target_statuses = {
            ApplicationStatus.READY_TO_APPLY,
            ApplicationStatus.PREPARED,
            ApplicationStatus.DRY_RUN_ONLY,
        } if bool(action.get("commit")) else {
            ApplicationStatus.READY_TO_APPLY,
            ApplicationStatus.PREPARED,
        }
        job_ids = [application.job_id for application in state.list_applications() if application.status in target_statuses]
        completed = _apply_jobs_for_ids(config, job_ids, commit=bool(action.get("commit")))
        console.print(f"Apply pipeline finished for {completed} jobs.")
        return {"_handled": True}
    if intent == "status":
        status()
        return {"_handled": True}
    if intent == "doctor":
        doctor()
        return {"_handled": True}
    if intent == "verify":
        _chat_verify(manager)
        return {"_handled": True}
    return None


def _chat_continue_action(manager: ConfigManager, action: dict[str, object], message: str) -> dict[str, object] | None:
    missing = [str(item) for item in action.get("missing", []) if item]
    if not missing:
        _execute_search_like_action(manager, action)
        return None
    field = missing[0]
    if field == "role":
        action["role"] = message.strip()
    elif field == "city":
        action["city"] = message.strip().title()
    remaining = [name for name in ("role", "city") if not action.get(name)]
    if remaining:
        action["missing"] = remaining
        _prompt_for_missing_field(remaining[0])
        return action
    action["missing"] = []
    _execute_search_like_action(manager, action)
    return None


def _execute_search_like_action(manager: ConfigManager, action: dict[str, object]) -> None:
    role = str(action.get("role", "")).strip()
    city = str(action.get("city", "")).strip()
    limit = int(action.get("limit", 25) or 25)
    config = manager.load()
    sources = [str(source).casefold() for source in action.get("sources", []) if source] or list(config.preferences.sources)
    if not sources:
        console.print("No job portals are enabled. Run `setup-portals` and enable at least one source.")
        return
    manager.update("preferences", {"role": role, "cities": [city], "sources": sources})
    config = manager.load()
    fetch_limit = min(max(limit * 2, limit), 200) if str(action.get("intent")) == "search_apply" else max(limit, 1)
    completed, qualified = _run_search_pipeline(config, role=role, city=city, sources=sources, limit=fetch_limit)
    console.print(f"Search finished: tasks={completed} qualified={qualified} sources={', '.join(sources)}")
    if str(action.get("intent")) != "search_apply":
        return
    selected = _select_jobs_for_apply(config, target_count=limit, sources=sources)
    if not selected:
        console.print("No matching jobs were ready for preparation.")
        return
    prepare_targets = [job_id for job_id in selected if _application_status(config, job_id) is ApplicationStatus.QUALIFIED]
    prepared = _prepare_jobs_for_ids(config, prepare_targets)
    applied = _apply_jobs_for_ids(config, selected, commit=True)
    console.print(
        f"Agent pipeline complete: selected={len(selected)} prepared={prepared} applied_or_attempted={applied}"
    )


def _prompt_for_missing_field(field: str) -> None:
    if field == "role":
        console.print("Which role should I search for?")
    elif field == "city":
        console.print("Which city should I target?")


def _select_portals_for_setup(current_sources: list[str]) -> list[str]:
    portals = available_portals()
    selected = {portal for portal in current_sources if portal in portals}
    if not sys.stdin.isatty():
        console.print("Interactive terminal required for portal selection.")
        return []
    cursor = 0
    while True:
        _render_portal_checklist(portals, selected, cursor)
        key = _read_single_key()
        if key in {"\r", "\n"}:
            console.print("")
            return [portal for portal in portals if portal in selected]
        if key in {"\x03", "\x1b"}:
            raise KeyboardInterrupt
        if key == " ":
            portal = portals[cursor]
            if portal in selected:
                selected.remove(portal)
            else:
                selected.add(portal)
            continue
        if key.casefold() == "a":
            if len(selected) == len(portals):
                selected.clear()
            else:
                selected = set(portals)
            continue
        if key == "UP":
            cursor = (cursor - 1) % len(portals)
            continue
        if key == "DOWN":
            cursor = (cursor + 1) % len(portals)
            continue


def _render_portal_checklist(portals: list[str], selected: set[str], cursor: int) -> None:
    lines = [
        "Available portals:",
        "",
    ]
    for index, portal in enumerate(portals, start=1):
        marker = "✓" if portal in selected else " "
        pointer = ">" if index - 1 == cursor else " "
        lines.append(f"{pointer} [{marker}] {PORTAL_DEFINITIONS[portal].label}")
    lines.extend(
        [
            "",
            "Select portals to configure",
            "(Use Up/Down to move, Space to toggle, A to toggle all, Enter to continue)",
        ]
    )
    output = "\n".join(lines)
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")
    console.print(output)


def _read_single_key() -> str:
    if os.name == "nt":
        import msvcrt

        while True:
            key = msvcrt.getwch()
            if key in {"\x00", "\xe0"}:
                special = msvcrt.getwch()
                if special == "H":
                    return "UP"
                if special == "P":
                    return "DOWN"
                continue
            return key
    return sys.stdin.read(1)


def _find_resume_source() -> Path | None:
    root = Path.cwd()
    for name in ("resume.json", "resume.txt", "resume.md"):
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def _ingest_resume_source(manager: ConfigManager, source_path: Path) -> dict[str, object]:
    if source_path.suffix.casefold() == ".json":
        raw = json.loads(source_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            payload: dict[str, object] = raw
        else:
            payload = {"summary": source_path.read_text(encoding="utf-8")}
    else:
        raw_text = source_path.read_text(encoding="utf-8")
        payload = AIAdapter(manager.load().ai).parse_resume_text(raw_text)
    if manager.load().ai.provider not in {"", "none"}:
        payload = AIAdapter(manager.load().ai).normalize_resume_profile(payload)
    return payload


def _confirm(prompt: str, *, default: bool) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    raw = input(prompt + suffix).strip().casefold()
    if not raw:
        return default
    return raw in {"y", "yes"}


def _prompt_text(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw or default


def _prompt_list(prompt: str, current: object) -> list[str]:
    default = ", ".join(str(item) for item in current) if isinstance(current, list) else ""
    raw = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    source = raw or default
    return [item.strip() for item in source.split(",") if item.strip()]


def _prompt_entries(title: str, current: object, fields: list[str]) -> list[dict[str, str]]:
    existing = current if isinstance(current, list) else []
    if existing and not _confirm(f"Edit existing {title.lower()}?", default=False):
        return [dict(item) for item in existing if isinstance(item, dict)]
    count_raw = input(f"{title} count [{len(existing)}]: ").strip()
    count = int(count_raw) if count_raw.isdigit() else len(existing)
    entries: list[dict[str, str]] = []
    for index in range(count):
        current_item = existing[index] if index < len(existing) and isinstance(existing[index], dict) else {}
        entry: dict[str, str] = {}
        for field_name in fields:
            entry[field_name] = _prompt_text(f"{title} #{index + 1} {field_name}", str(current_item.get(field_name, "")))
        entries.append({key: value for key, value in entry.items() if value})
    return entries


def config_manager_path(manager: ConfigManager) -> Path:
    return manager.path


def _select_provider(current: str) -> str:
    console.print("Select AI provider:")
    for value, label in AI_PROVIDER_CHOICES:
        console.print(f"- {value}: {label}")
    default_value = current or AI_PROVIDER_CHOICES[0][0]
    lookup = {value.casefold(): value for value, _ in AI_PROVIDER_CHOICES}
    lookup.update({label.casefold(): value for value, label in AI_PROVIDER_CHOICES})
    while True:
        raw = input(f"Provider [{default_value}]: ").strip()
        if not raw:
            return default_value
        mapped = lookup.get(raw.casefold())
        if mapped:
            return mapped
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
    for model in presets:
        console.print(f"- {model}")
    default_model = current or (presets[0] if presets else "")
    while True:
        raw = input(f"Model [{default_model}]: ").strip()
        if not raw:
            return default_model
        if raw in presets:
            return raw
        if raw:
            return raw
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


def main() -> None:
    if len(sys.argv) == 1:
        chat()
        return
    app()


if __name__ == "__main__":
    main()
