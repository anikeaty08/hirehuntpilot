"""Deterministic Telegram tools exposed to the control agent."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from hirehuntpilot import config
from hirehuntpilot.database import get_connection, get_jobs_by_stage, get_stats, init_db


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: dict[str, str]
    handler: Callable

    def to_prompt_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "args": self.args,
        }


def _bootstrap() -> None:
    config.load_env()
    config.ensure_dirs()
    init_db()


def _router_model_name() -> str:
    return config.get_agent_model("telegram_router")


def _load_agent_model_summary() -> str:
    provider = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    model = (os.environ.get("LLM_MODEL") or "").strip()
    if not provider:
        return "AI provider is not configured."
    return f"{provider.capitalize()} ({model or 'default model'})"


def get_status() -> str:
    _bootstrap()
    stats = get_stats()
    return "\n".join(
        [
            "Job pipeline status",
            f"Total discovered: {stats.get('total', 0)}",
            f"Pending enrichment: {stats.get('pending_detail', 0)}",
            f"With description: {stats.get('with_description', 0)}",
            f"Pending scoring: {stats.get('unscored', 0)}",
            f"Scored: {stats.get('scored', 0)}",
            f"Tailored: {stats.get('tailored', 0)}",
            f"Ready to apply: {stats.get('ready_to_apply', 0)}",
            f"Applied: {stats.get('applied', 0)}",
            f"Apply errors: {stats.get('apply_errors', 0)}",
        ]
    )


def query_jobs(
    stage: str = "scored",
    min_score: int = 0,
    limit: int = 5,
    include_urls: bool = True,
) -> str:
    _bootstrap()
    rows = get_jobs_by_stage(stage=stage, min_score=min_score, limit=max(1, min(limit, 20)))
    if not rows:
        return f"No jobs found for stage '{stage}' with min_score={min_score}."

    lines = [f"Jobs for stage '{stage}'"]
    for index, row in enumerate(rows, 1):
        score = row.get("fit_score")
        score_text = str(score) if score is not None else "?"
        status_text = row.get("apply_status") or "discovered"
        lines.append(
            f"{index}. {row.get('title') or 'Untitled job'} @ {row.get('site') or 'Unknown'} "
            f"- score {score_text} [{status_text}]"
        )
        if include_urls and row.get("url"):
            lines.append(f"URL: {row['url']}")
    return "\n".join(lines)


def list_jobs(min_score: int = 0, limit: int = 10) -> str:
    return query_jobs(stage="scored", min_score=min_score, limit=limit, include_urls=True)


def get_failed_jobs(limit: int = 5) -> str:
    _bootstrap()
    conn = get_connection(config.DB_PATH)
    rows = conn.execute(
        "SELECT title, site, apply_error FROM jobs "
        "WHERE apply_error IS NOT NULL AND apply_error != '' "
        "ORDER BY last_attempted_at DESC LIMIT ?",
        (max(1, min(limit, 20)),),
    ).fetchall()
    if not rows:
        return "No failed jobs recorded."

    lines = ["Recent failed jobs"]
    for row in rows:
        lines.append(
            f"- {row['title'] or 'Untitled job'} @ {row['site'] or 'Unknown'}: {(row['apply_error'] or 'unknown')[:160]}"
        )
    return "\n".join(lines)


def get_recent_applied(limit: int = 5) -> str:
    _bootstrap()
    conn = get_connection(config.DB_PATH)
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = conn.execute(
        "SELECT title, site, applied_at FROM jobs "
        "WHERE applied_at IS NOT NULL AND applied_at >= ? "
        "ORDER BY applied_at DESC LIMIT ?",
        (since, max(1, min(limit, 20))),
    ).fetchall()
    if not rows:
        return "No recent applied jobs in the last 7 days."

    lines = ["Recently applied jobs"]
    for row in rows:
        lines.append(f"- {row['title'] or 'Untitled job'} @ {row['site'] or 'Unknown'} on {(row['applied_at'] or '')[:16]}")
    return "\n".join(lines)


def get_search_config() -> str:
    cfg = config.load_search_config()
    queries = [item.get("query", "").strip() for item in cfg.get("queries", []) if item.get("query")]
    sources = [str(item).strip() for item in (cfg.get("sources") or cfg.get("boards") or []) if str(item).strip()]
    locations = [item.get("location", "").strip() for item in cfg.get("locations", []) if item.get("location")]
    return "\n".join(
        [
            "Active search config",
            f"Queries: {', '.join(queries) if queries else 'none'}",
            f"Sources: {', '.join(sources) if sources else 'default sources'}",
            f"Locations: {', '.join(locations) if locations else 'none'}",
        ]
    )


def get_ai_config() -> str:
    _bootstrap()
    return f"AI provider: {_load_agent_model_summary()}"


def get_runtime_info() -> str:
    return "\n".join(
        [
            f"App dir: {config.APP_DIR}",
            f"DB: {config.DB_PATH}",
            f"Profile: {config.PROFILE_PATH}",
            f"Search config: {config.SEARCH_CONFIG_PATH}",
            f"Model config: {config.MODEL_CONFIG_PATH}",
        ]
    )


def get_telegram_config() -> str:
    from hirehuntpilot.wizard.init import check_telegram

    configured, info = check_telegram()
    return f"Telegram setup: {info}" if configured else "Telegram is not configured."


def run_discover(job_titles: list[str] | None = None, locations: list[str] | None = None) -> str:
    _bootstrap()
    from hirehuntpilot.discovery.hirehunt import run_discovery

    current_cfg = config.load_search_config()
    override_cfg = {
        "queries": [{"query": title} for title in (job_titles or []) if title],
        "locations": [{"location": location} for location in (locations or []) if location],
        "sources": current_cfg.get("sources") or current_cfg.get("boards") or ["linkedin", "naukri", "indeed"],
        "defaults": current_cfg.get("defaults", {}),
    }
    if not override_cfg["queries"]:
        override_cfg["queries"] = current_cfg.get("queries", [])
    if not override_cfg["locations"]:
        override_cfg["locations"] = current_cfg.get("locations", [])

    result = run_discovery(cfg=override_cfg)
    lines = [
        f"Discovery complete. New jobs: {result.get('new', 0)}",
        f"Existing jobs: {result.get('existing', 0)}",
    ]
    for job in result.get("preview_jobs", [])[:5]:
        lines.append(f"- {job.get('title') or 'Untitled job'} @ {job.get('site') or 'unknown'}")
    return "\n".join(lines)


def run_stage(stage: str, min_score: int = 7) -> str:
    _bootstrap()
    from hirehuntpilot.pipeline import run_pipeline

    if stage not in {"enrich", "score", "tailor", "cover", "pdf"}:
        return f"Unsupported stage: {stage}"
    result = run_pipeline(stages=[stage], min_score=min_score, dry_run=False, workers=1)
    if result.get("errors"):
        return f"{stage} failed: {result['errors']}"
    return f"{stage} completed.\n{get_status()}"


def run_apply(limit: int = 1, min_score: int = 7) -> str:
    _bootstrap()
    from hirehuntpilot.apply.launcher import main as apply_main

    apply_main(limit=max(1, min(limit, 5)), min_score=min_score, headless=True)
    return f"Apply complete.\n{get_status()}"


def update_profile(instruction: str, model_config_name: str | None = None) -> str:
    from hirehuntpilot.config import PROFILE_PATH, invoke_agentscope_model, load_agentscope_model

    if not PROFILE_PATH.exists():
        return "Profile file not found."
    try:
        current_profile = PROFILE_PATH.read_text(encoding="utf-8")
        prompt = f"""You are a profile update assistant.
Here is the candidate's current profile JSON:
{current_profile}

The user gave this update command:
"{instruction}"

Return the new, fully updated profile JSON (retaining all unchanged fields).
Output ONLY valid JSON, no markdown fences, no explanation.
"""
        model = load_agentscope_model(model_config_name or _router_model_name())
        response = invoke_agentscope_model(model, [{"role": "user", "content": prompt}])
        text = (response.text or "").strip().strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        updated_data = json.loads(text)
        PROFILE_PATH.write_text(json.dumps(updated_data, indent=2, ensure_ascii=False), encoding="utf-8")
        return "Profile updated successfully."
    except Exception as exc:
        return f"Failed to update profile: {exc}"


def update_resume(instruction: str, model_config_name: str | None = None) -> str:
    from hirehuntpilot.config import RESUME_PATH, invoke_agentscope_model, load_agentscope_model

    if not RESUME_PATH.exists():
        return "Resume file not found."
    try:
        current_resume = RESUME_PATH.read_text(encoding="utf-8")
        prompt = f"""You are a resume editor assistant.
Here is the candidate's current resume text:
{current_resume}

The user wants to update it:
"{instruction}"

Return the fully updated resume text. Retain all original formatting, content, and sections except for the requested changes.
Output ONLY the new resume text, no explanation.
"""
        model = load_agentscope_model(model_config_name or _router_model_name())
        response = invoke_agentscope_model(model, [{"role": "user", "content": prompt}])
        text = (response.text or "").strip()
        RESUME_PATH.write_text(text, encoding="utf-8")
        return "Resume updated successfully."
    except Exception as exc:
        return f"Failed to update resume: {exc}"


def help_overview() -> str:
    return "\n".join(
        [
            "Supported requests:",
            "- greetings like hey/hello",
            "- status questions",
            "- top jobs / stage-based job lists / failed jobs / recent applies",
            "- active queries, sources, runtime paths, AI config",
            "- actions like discover, enrich, score, tailor, cover, pdf, apply",
            "- update profile or resume",
        ]
    )


TOOL_REGISTRY = [
    ToolSpec("get_status", "Read pipeline counts from the SQLite database.", {}, get_status),
    ToolSpec(
        "query_jobs",
        "List jobs from the SQLite database for a logical pipeline stage.",
        {"stage": "str optional", "min_score": "int optional", "limit": "int optional", "include_urls": "bool optional"},
        query_jobs,
    ),
    ToolSpec("list_jobs", "List top scored jobs from the SQLite database.", {"min_score": "int optional", "limit": "int optional"}, list_jobs),
    ToolSpec("get_failed_jobs", "Show recent failed application reasons from the database.", {"limit": "int optional"}, get_failed_jobs),
    ToolSpec("get_recent_applied", "Show recently applied jobs from the database.", {"limit": "int optional"}, get_recent_applied),
    ToolSpec("get_search_config", "Show active queries, sources, and locations.", {}, get_search_config),
    ToolSpec("get_ai_config", "Show the configured AI provider and model.", {}, get_ai_config),
    ToolSpec("get_runtime_info", "Show runtime file paths including DB and profile.", {}, get_runtime_info),
    ToolSpec("get_telegram_config", "Show whether Telegram is configured.", {}, get_telegram_config),
    ToolSpec(
        "run_discover",
        "Run job discovery. Optional job_titles and locations can override the saved search config.",
        {"job_titles": "list[str] optional", "locations": "list[str] optional"},
        run_discover,
    ),
    ToolSpec(
        "run_stage",
        "Run one pipeline stage: enrich, score, tailor, cover, or pdf.",
        {"stage": "str required", "min_score": "int optional"},
        run_stage,
    ),
    ToolSpec("run_apply", "Run auto-apply for a limited number of jobs.", {"limit": "int optional", "min_score": "int optional"}, run_apply),
    ToolSpec("update_profile", "Use the model to update profile.json from the user's instruction.", {"instruction": "str required"}, update_profile),
    ToolSpec("update_resume", "Use the model to update resume.txt from the user's instruction.", {"instruction": "str required"}, update_resume),
    ToolSpec("help_overview", "Return a short help message describing supported requests.", {}, help_overview),
]

TOOLS = {tool.name: tool.handler for tool in TOOL_REGISTRY}


def tool_specs() -> list[dict]:
    return [tool.to_prompt_dict() for tool in TOOL_REGISTRY]
