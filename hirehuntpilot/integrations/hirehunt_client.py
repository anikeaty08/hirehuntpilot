from __future__ import annotations

import hashlib
from typing import Any

from hirehuntpilot.models import JobRecord


class HireHuntClient:
    def search(self, *, query: str, cities: list[str], sources: list[str], limit: int = 25) -> list[JobRecord]:
        if not sources:
            return []
        try:
            from hirehunt import scrape_jobs
        except ImportError:
            return self._fallback_jobs(query=query, cities=cities, sources=sources, limit=limit)
        try:
            kwargs: dict[str, Any] = {
                "search_term": query,
                "sources": sources,
                "results_wanted": limit,
            }
            if cities:
                kwargs["city"] = cities[0]

            result = scrape_jobs(**kwargs)
            jobs: list[JobRecord] = []
            for raw in getattr(result, "jobs", []):
                title = _stringify(getattr(raw, "title", "") or "")
                company = _stringify(getattr(raw, "company", "") or "")
                source = _stringify(getattr(raw, "source", "") or "")
                url = _stringify(getattr(raw, "job_url", "") or "")
                source_job_id = getattr(raw, "source_job_id", "") or f"{source}:{company}:{title}:{url}"
                jobs.append(
                    JobRecord(
                        source_job_id=_stringify(source_job_id),
                        title=title,
                        company=company,
                        source=source,
                        job_url=url,
                        apply_url=_optional_string(getattr(raw, "apply_url", None)),
                        location=_stringify(getattr(raw, "location", "") or ""),
                        city=_stringify(getattr(raw, "city", "") or ""),
                        country=_stringify(getattr(raw, "country", "India") or "India"),
                        work_mode=_stringify(getattr(raw, "work_mode", "unknown") or "unknown"),
                        job_kind=_stringify(getattr(raw, "job_kind", "job") or "job"),
                        experience=_stringify(getattr(raw, "experience_text", "") or ""),
                        salary=_stringify(getattr(raw, "salary", "") or ""),
                        stipend=_stringify(getattr(raw, "stipend", "") or ""),
                        skills=[_stringify(skill) for skill in list(getattr(raw, "skills", []) or [])],
                        description=_stringify(getattr(raw, "description", "") or ""),
                        easy_apply=bool(getattr(raw, "apply_url", None)),
                        match_score=float(getattr(raw, "match_score", 0.0) or 0.0),
                    )
                )
        except Exception:
            return self._fallback_jobs(query=query, cities=cities, sources=sources, limit=limit)
        if jobs:
            return jobs
        return self._fallback_jobs(query=query, cities=cities, sources=sources, limit=limit)

    def _fallback_jobs(self, *, query: str, cities: list[str], sources: list[str], limit: int) -> list[JobRecord]:
        city = cities[0] if cities else "Bengaluru"
        active_sources = list(sources)
        if not active_sources:
            return []
        jobs: list[JobRecord] = []
        max_jobs = max(1, min(limit, len(active_sources) * 3))
        for index, source in enumerate(active_sources[:max_jobs]):
            title = query.title()
            company = f"Sample {source.title()} Company {index + 1}"
            url = f"https://example.com/{source}/{index + 1}"
            digest = hashlib.sha1(f"{source}:{title}:{company}".encode("utf-8")).hexdigest()[:12]
            jobs.append(
                JobRecord(
                    source_job_id=f"{source}:{digest}",
                    title=title,
                    company=company,
                    source=source,
                    job_url=url,
                    apply_url=f"{url}/apply",
                    location=city,
                    city=city,
                    country="India",
                    work_mode="hybrid" if index % 2 else "remote",
                    job_kind="job",
                    experience="0-2 yrs",
                    salary="INR 6-10 LPA",
                    skills=[query.split()[0] if query.split() else "python", "sql", "communication"],
                    description=f"Fallback job for {query} from {source}.",
                    easy_apply=True,
                    match_score=80.0 - index,
                    metadata={"fallback": True},
                )
            )
            if len(jobs) >= limit:
                break
        return jobs


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
