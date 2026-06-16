from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from hirehuntpilot import config
from hirehuntpilot.database import get_connection, init_db

log = logging.getLogger(__name__)


def run_discovery(cfg: dict | None = None) -> dict[str, Any]:
    """Discover jobs through hirehunt and store them in SQLite."""
    if cfg is None:
        cfg = config.load_search_config()

    queries = [item.get("query", "").strip() for item in cfg.get("queries", []) if item.get("query")]
    if not queries:
        queries = ["python developer"]

    cities = [item.get("location", "").strip() for item in cfg.get("locations", []) if item.get("location")]
    if not cities:
        cities = ["Bengaluru"]

    sources = cfg.get("sources") or cfg.get("boards") or ["linkedin", "naukri", "indeed"]
    limit_per_query = int(cfg.get("defaults", {}).get("results_per_source", cfg.get("defaults", {}).get("results_per_site", 25)))

    init_db()
    conn = get_connection()

    total_new = 0
    total_existing = 0
    total_queries = 0
    all_errors: list[str] = []
    all_warnings: list[str] = []
    used_fallback = False
    any_live_success = False
    selected_sources: list[str] = []

    for query in queries:
        total_queries += 1
        outcome = search_hirehunt(query=query, cities=cities, sources=sources, limit=limit_per_query)
        jobs = outcome["jobs"]
        result_info = outcome["result"]

        new_count, existing_count = _store_jobs(conn, jobs)
        total_new += new_count
        total_existing += existing_count

        all_errors.extend(result_info.get("errors", []))
        all_warnings.extend(result_info.get("warnings", []))
        used_fallback = used_fallback or bool(result_info.get("fallback_used"))
        any_live_success = any_live_success or bool(result_info.get("live_success"))
        selected_sources = result_info.get("selected_sources") or selected_sources

        log.info(
            "hirehunt query '%s' returned %d jobs (%d new, %d existing)%s",
            query,
            len(jobs),
            new_count,
            existing_count,
            " via fallback" if result_info.get("fallback_used") else "",
        )

    blocked = _is_live_access_blocked(all_errors)
    status = "ok"
    if all_errors and not any_live_success:
        status = "partial" if used_fallback else "error"
    elif used_fallback:
        status = "partial"

    return {
        "status": status,
        "queries": total_queries,
        "new": total_new,
        "existing": total_existing,
        "errors": all_errors,
        "warnings": all_warnings,
        "fallback_used": used_fallback,
        "live_success": any_live_success,
        "live_access_blocked": blocked,
        "selected_sources": selected_sources or list(sources),
    }


def diagnose_hirehunt(cfg: dict | None = None) -> dict[str, Any]:
    """Run a light hirehunt diagnostic without writing to the database."""
    if cfg is None:
        cfg = config.load_search_config()

    queries = [item.get("query", "").strip() for item in cfg.get("queries", []) if item.get("query")]
    cities = [item.get("location", "").strip() for item in cfg.get("locations", []) if item.get("location")]
    sources = cfg.get("sources") or cfg.get("boards") or ["linkedin", "naukri", "indeed"]

    query = queries[0] if queries else "python developer"
    city = cities[0] if cities else "Bengaluru"

    outcome = search_hirehunt(query=query, cities=[city], sources=sources, limit=1)
    result_info = outcome["result"]

    return {
        "query": query,
        "city": city,
        "selected_sources": result_info.get("selected_sources") or list(sources),
        "errors": result_info.get("errors", []),
        "warnings": result_info.get("warnings", []),
        "partial": bool(result_info.get("partial")),
        "fallback_used": bool(result_info.get("fallback_used")),
        "live_success": bool(result_info.get("live_success")),
        "live_access_blocked": _is_live_access_blocked(result_info.get("errors", [])),
        "job_count": len(outcome["jobs"]),
    }


def search_hirehunt(*, query: str, cities: list[str], sources: list[str], limit: int) -> dict[str, Any]:
    """Run one hirehunt search and return normalized jobs plus result metadata."""
    if not sources:
        return {"jobs": [], "result": {"errors": [], "warnings": [], "partial": False, "selected_sources": [], "fallback_used": False, "live_success": False}}

    try:
        from hirehunt import scrape_jobs
    except ImportError:
        return {
            "jobs": _fallback_jobs(query=query, cities=cities, sources=sources, limit=limit),
            "result": {
                "errors": ["hirehunt package not installed"],
                "warnings": [],
                "partial": True,
                "selected_sources": list(sources),
                "fallback_used": True,
                "live_success": False,
            },
        }

    kwargs: dict[str, Any] = {
        "search_term": query,
        "sources": sources,
        "results_wanted": limit,
    }
    if cities:
        kwargs["city"] = cities[0]

    try:
        result = scrape_jobs(**kwargs)
    except Exception as exc:
        return {
            "jobs": _fallback_jobs(query=query, cities=cities, sources=sources, limit=limit),
            "result": {
                "errors": [str(exc)],
                "warnings": [],
                "partial": True,
                "selected_sources": list(sources),
                "fallback_used": True,
                "live_success": False,
            },
        }

    errors = [_string(err) for err in list(getattr(result, "errors", []) or [])]
    warnings = [_string(warn) for warn in list(getattr(result, "warnings", []) or [])]
    jobs = _normalize_jobs(result=result, cities=cities)
    live_success = bool(jobs)
    fallback_used = False

    if not jobs:
        jobs = _fallback_jobs(query=query, cities=cities, sources=sources, limit=limit)
        fallback_used = True

    return {
        "jobs": jobs,
        "result": {
            "errors": errors,
            "warnings": warnings,
            "partial": bool(getattr(result, "partial", False)),
            "selected_sources": list(getattr(result, "selected_sources", []) or list(sources)),
            "stats": getattr(result, "stats", None),
            "schema_version": getattr(result, "schema_version", None),
            "fallback_used": fallback_used,
            "live_success": live_success,
        },
    }


def _normalize_jobs(*, result: Any, cities: list[str]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for raw in getattr(result, "jobs", []) or []:
        job_url = _string(getattr(raw, "job_url", "") or "")
        if not job_url:
            continue
        description = _string(getattr(raw, "description", "") or "")
        apply_url = _optional_string(getattr(raw, "apply_url", None))
        location = _string(getattr(raw, "location", "") or "")
        city = _string(getattr(raw, "city", "") or "")
        source = _string(getattr(raw, "source", "") or "")
        title = _string(getattr(raw, "title", "") or "")
        salary = _string(getattr(raw, "salary", "") or "") or _string(getattr(raw, "stipend", "") or "")
        jobs.append(
            {
                "url": job_url,
                "title": title,
                "salary": salary or None,
                "description": description or None,
                "location": location or city or (cities[0] if cities else None),
                "site": source or "hirehunt",
                "strategy": "hirehunt",
                "application_url": apply_url,
                "full_description": description or None,
            }
        )
    return jobs


def _store_jobs(conn, jobs: list[dict[str, Any]]) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    existing = 0

    for job in jobs:
        try:
            conn.execute(
                """
                INSERT INTO jobs (
                    url, title, salary, description, location, site, strategy, discovered_at,
                    full_description, application_url, detail_scraped_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job["url"],
                    job.get("title"),
                    job.get("salary"),
                    job.get("description"),
                    job.get("location"),
                    job.get("site"),
                    job.get("strategy", "hirehunt"),
                    now,
                    job.get("full_description"),
                    job.get("application_url"),
                    now if job.get("full_description") else None,
                ),
            )
            new += 1
        except Exception:
            existing += 1

    conn.commit()
    return new, existing


def _fallback_jobs(*, query: str, cities: list[str], sources: list[str], limit: int) -> list[dict[str, Any]]:
    city = cities[0] if cities else "Bengaluru"
    rows: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        if len(rows) >= limit:
            break
        title = query.title()
        company = f"Sample {source.title()} Company {index + 1}"
        url = f"https://example.com/{source}/{index + 1}"
        digest = hashlib.sha1(f"{source}:{title}:{company}".encode("utf-8")).hexdigest()[:12]
        rows.append(
            {
                "url": f"{url}?id={digest}",
                "title": title,
                "salary": "INR 6-10 LPA",
                "description": f"Fallback hirehunt job for {query} from {source}.",
                "location": city,
                "site": source,
                "strategy": "hirehunt-fallback",
                "application_url": f"{url}/apply",
                "full_description": f"Fallback hirehunt job for {query} from {source}.",
            }
        )
    return rows


def _is_live_access_blocked(errors: list[str]) -> bool:
    haystack = " ".join(errors).lower()
    blocked_signals = [
        "winerror 10013",
        "forbidden by its access permissions",
        "failed to establish a new connection",
        "max retries exceeded",
    ]
    return any(signal in haystack for signal in blocked_signals)


def _string(value: Any) -> str:
    return "" if value is None else str(value)


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
