from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hirehuntpilot.compat import dump_data
from hirehuntpilot.config import PersonalConfig, ResumeConfig


def load_resume_data(resume_json_path: str | Path) -> dict[str, Any]:
    path = Path(resume_json_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def render_resume_text(resume_json_path: str | Path) -> str:
    data = load_resume_data(resume_json_path)
    return render_resume_text_data(data)


def render_resume_text_data(data: dict[str, Any]) -> str:
    if not data:
        return ""
    sections: list[str] = []
    for key in ["name", "summary"]:
        value = data.get(key)
        if value:
            sections.append(str(value))
    for key in ["skills", "experience", "projects", "education"]:
        value = data.get(key)
        if value:
            sections.append(f"{key.title()}: {value}")
    return "\n\n".join(sections)


def build_rendercv_payload(
    resume_data: dict[str, Any],
    personal: PersonalConfig,
    resume_config: ResumeConfig,
    *,
    summary_override: str | None = None,
) -> dict[str, Any]:
    payload = {
        "cv": {
            "name": resume_data.get("name") or personal.name,
            "headline": resume_data.get("headline") or resume_data.get("title") or "",
            "location": resume_data.get("location") or "",
            "email": personal.email or None,
            "phone": personal.phone or None,
            "website": personal.portfolio or None,
            "social_networks": _build_social_networks(personal),
            "sections": {},
        },
        "design": {
            "theme": resume_config.rendercv_theme or "classic",
        },
        "locale": {
            "language": "english",
        },
        "settings": {},
    }

    summary_text = summary_override or resume_data.get("summary")
    if summary_text:
        payload["cv"]["sections"]["Profile"] = [summary_text]

    experience_entries = _normalize_experience_entries(resume_data.get("experience"))
    if experience_entries:
        payload["cv"]["sections"]["Experience"] = experience_entries

    project_entries = _normalize_project_entries(resume_data.get("projects"))
    if project_entries:
        payload["cv"]["sections"]["Projects"] = project_entries

    education_entries = _normalize_education_entries(resume_data.get("education"))
    if education_entries:
        payload["cv"]["sections"]["Education"] = education_entries

    skill_entries = _normalize_skill_entries(resume_data.get("skills"))
    if skill_entries:
        payload["cv"]["sections"]["Skills"] = skill_entries

    return payload


def write_rendercv_yaml(
    resume_json_path: str | Path,
    output_path: str | Path,
    personal: PersonalConfig,
    resume_config: ResumeConfig,
    *,
    summary_override: str | None = None,
) -> Path:
    resume_data = load_resume_data(resume_json_path)
    payload = build_rendercv_payload(
        resume_data,
        personal,
        resume_config,
        summary_override=summary_override,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(dump_data(payload), encoding="utf-8")
    return output


def _build_social_networks(personal: PersonalConfig) -> list[dict[str, str]] | None:
    items: list[dict[str, str]] = []
    if personal.linkedin:
        items.append({"network": "LinkedIn", "username": _social_username(personal.linkedin)})
    if personal.github:
        items.append({"network": "GitHub", "username": _social_username(personal.github)})
    return items or None


def _social_username(value: str) -> str:
    trimmed = value.rstrip("/")
    return trimmed.rsplit("/", 1)[-1] if "/" in trimmed else trimmed


def _normalize_experience_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            company = item.get("company") or item.get("name") or "Experience"
            position = item.get("position") or item.get("role") or item.get("title") or ""
            entry: dict[str, Any] = {
                "company": str(company),
                "position": str(position),
            }
            _assign_shared_fields(entry, item)
            entries.append(entry)
        else:
            entries.append({"company": "Experience", "position": "", "summary": str(item)})
    return entries


def _normalize_project_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            entry = {"name": str(item.get("name") or item.get("title") or "Project")}
            _assign_shared_fields(entry, item)
            entries.append(entry)
        else:
            entries.append({"name": str(item)})
    return entries


def _normalize_education_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            entry: dict[str, Any] = {
                "institution": str(item.get("institution") or item.get("school") or "Education"),
                "area": str(item.get("area") or item.get("field") or item.get("degree") or ""),
            }
            if item.get("degree"):
                entry["degree"] = str(item["degree"])
            _assign_shared_fields(entry, item)
            entries.append(entry)
        else:
            entries.append({"institution": str(item), "area": ""})
    return entries


def _normalize_skill_entries(value: Any) -> list[dict[str, str]]:
    if isinstance(value, list):
        details = ", ".join(str(item) for item in value if item)
        return [{"label": "Skills", "details": details}] if details else []
    if isinstance(value, dict):
        entries = []
        for key, item in value.items():
            if isinstance(item, list):
                details = ", ".join(str(part) for part in item if part)
            else:
                details = str(item)
            if details:
                entries.append({"label": str(key).title(), "details": details})
        return entries
    if value:
        return [{"label": "Skills", "details": str(value)}]
    return []


def _assign_shared_fields(entry: dict[str, Any], item: dict[str, Any]) -> None:
    for source_key, target_key in (
        ("date", "date"),
        ("start_date", "start_date"),
        ("end_date", "end_date"),
        ("location", "location"),
        ("summary", "summary"),
    ):
        value = item.get(source_key)
        if value:
            entry[target_key] = str(value)
    highlights = item.get("highlights")
    if isinstance(highlights, list):
        cleaned = [str(part) for part in highlights if part]
        if cleaned:
            entry["highlights"] = cleaned
