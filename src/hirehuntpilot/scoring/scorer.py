"""Opportunity fit scoring: batch-aware LLM evaluation for jobs and related opportunities."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from hirehuntpilot.config import RESUME_PATH
from hirehuntpilot.database import get_connection, get_jobs_by_stage, init_db
from hirehuntpilot.llm import get_role_client
from hirehuntpilot.opportunities import classify_opportunity

log = logging.getLogger(__name__)

SCORE_PROMPT = """You are an opportunity fit evaluator. Given a candidate's resume and one opportunity description, score how well the candidate fits it.

Opportunity types can be:
- job
- internship
- hackathon
- challenge

SCORING CRITERIA:
- 9-10: Perfect match. Candidate has direct experience in nearly all required skills and qualifications.
- 7-8: Strong match. Candidate has most required skills, minor gaps easily bridged.
- 5-6: Moderate match. Candidate has some relevant skills but missing key requirements.
- 3-4: Weak match. Significant skill gaps, would need substantial ramp-up.
- 1-2: Poor match. Completely different field or experience level.

IMPORTANT FACTORS:
- Weight technical skills heavily.
- Consider transferable experience.
- Be realistic about experience level vs. job requirements.
- Distinguish normal jobs from internships and hackathons/challenges.

RESPOND IN EXACTLY THIS FORMAT:
TYPE: [job|internship|hackathon|challenge]
SCORE: [1-10]
KEYWORDS: [comma-separated ATS keywords]
REASONING: [2-3 sentences]"""

_BATCH_SCORE_PROMPT = """You are an opportunity ranking engine. You will receive one candidate resume and a batch of opportunities.

For each opportunity:
- classify the opportunity type as one of: job, internship, hackathon, challenge
- assign a fit score from 1 to 10
- extract 3 to 8 matching keywords
- provide a short reasoning

Scoring rules:
- 9-10: excellent direct fit
- 7-8: strong fit
- 5-6: moderate fit
- 3-4: weak fit
- 1-2: poor fit

Return ONLY valid JSON in this exact shape:
{"results":[
  {
    "job_url":"...",
    "opportunity_type":"job",
    "score":7,
    "keywords":["python","fastapi","apis"],
    "reasoning":"..."
  }
]}

Every input job_url must appear exactly once in the output."""


def _extract_json(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
    raise ValueError("No valid JSON found in LLM response")


def _normalize_keywords(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _normalize_opportunity_type(value: Any, job: dict) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in {"job", "internship", "hackathon", "challenge"}:
        return candidate
    inferred = classify_opportunity(job)
    return str(inferred["opportunity_type"])


def _parse_score_response(response: str, job: dict) -> dict[str, Any]:
    score = 0
    keywords = ""
    reasoning = response
    opportunity_type = ""

    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("TYPE:"):
            opportunity_type = line.replace("TYPE:", "").strip().lower()
        elif line.startswith("SCORE:"):
            try:
                score = int(re.search(r"\d+", line).group())
                score = max(1, min(10, score))
            except (AttributeError, ValueError):
                score = 0
        elif line.startswith("KEYWORDS:"):
            keywords = line.replace("KEYWORDS:", "").strip()
        elif line.startswith("REASONING:"):
            reasoning = line.replace("REASONING:", "").strip()

    return {
        "score": score,
        "keywords": keywords,
        "reasoning": reasoning,
        "opportunity_type": _normalize_opportunity_type(opportunity_type, job),
    }


def _compact_job_text(job: dict, description_limit: int = 1400) -> str:
    insight = classify_opportunity(job)
    description = (job.get("full_description") or "")[:description_limit]
    return (
        f"URL: {job['url']}\n"
        f"TITLE: {job['title']}\n"
        f"SOURCE: {job['site']}\n"
        f"LOCATION: {job.get('location', 'N/A')}\n"
        f"HEURISTIC_TYPE: {insight['opportunity_type']}\n"
        f"DESCRIPTION:\n{description}"
    )


def score_job(resume_text: str, job: dict) -> dict[str, Any]:
    job_text = _compact_job_text(job, description_limit=6000)
    messages = [
        {"role": "system", "content": SCORE_PROMPT},
        {"role": "user", "content": f"RESUME:\n{resume_text}\n\n---\n\nOPPORTUNITY:\n{job_text}"},
    ]

    try:
        client = get_role_client("scoring")
        response = client.chat(messages, max_tokens=512, temperature=0.2)
        return _parse_score_response(response, job)
    except Exception as exc:
        log.error("LLM error scoring job '%s': %s", job.get("title", "?"), exc)
        inferred = classify_opportunity(job)
        return {
            "score": 0,
            "keywords": "",
            "reasoning": f"LLM error: {exc}",
            "opportunity_type": inferred["opportunity_type"],
        }


def score_jobs_batch(resume_text: str, jobs: list[dict], batch_size: int = 10) -> list[dict[str, Any]]:
    if not jobs:
        return []

    batch_size = max(1, min(batch_size, 50))
    client = get_role_client("scoring")
    results: list[dict[str, Any]] = []

    for start in range(0, len(jobs), batch_size):
        chunk = jobs[start:start + batch_size]
        chunk_body = "\n\n".join(
            f"OPPORTUNITY {index + 1}\n{_compact_job_text(job)}"
            for index, job in enumerate(chunk)
        )
        messages = [
            {"role": "system", "content": _BATCH_SCORE_PROMPT},
            {"role": "user", "content": f"RESUME:\n{resume_text}\n\n---\n\nBATCH:\n{chunk_body}"},
        ]

        parsed_by_url: dict[str, dict[str, Any]] = {}
        try:
            response = client.chat(messages, max_tokens=4096, temperature=0.2)
            payload = _extract_json(response)
            raw_results = payload.get("results", []) if isinstance(payload, dict) else []
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("job_url") or "").strip()
                if not url:
                    continue
                source_job = next((job for job in chunk if job["url"] == url), None)
                if source_job is None:
                    continue
                parsed_by_url[url] = {
                    "url": url,
                    "score": max(1, min(10, int(item.get("score", 0) or 0))) if str(item.get("score", "")).strip() else 0,
                    "keywords": _normalize_keywords(item.get("keywords")),
                    "reasoning": str(item.get("reasoning") or "").strip() or "No reasoning returned.",
                    "opportunity_type": _normalize_opportunity_type(item.get("opportunity_type"), source_job),
                }
        except Exception as exc:
            log.warning("Batch scoring failed for %d opportunities: %s", len(chunk), exc)

        for job in chunk:
            result = parsed_by_url.get(job["url"])
            if result is None:
                single = score_job(resume_text, job)
                single["url"] = job["url"]
                result = single
            results.append(result)

    return results


def run_scoring(limit: int = 0, rescore: bool = False, batch_size: int = 10) -> dict:
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    init_db()
    conn = get_connection()

    if rescore:
        query = "SELECT * FROM jobs WHERE full_description IS NOT NULL"
        if limit > 0:
            query += f" LIMIT {limit}"
        jobs = conn.execute(query).fetchall()
    else:
        jobs = get_jobs_by_stage(conn=conn, stage="pending_score", limit=limit)

    if not jobs:
        log.info("No unscored jobs with descriptions found.")
        return {"scored": 0, "errors": 0, "elapsed": 0.0, "distribution": []}

    if jobs and not isinstance(jobs[0], dict):
        columns = jobs[0].keys()
        jobs = [dict(zip(columns, row)) for row in jobs]

    log.info("Scoring %d opportunities in batches of %d...", len(jobs), max(1, min(batch_size, 50)))
    t0 = time.time()
    results = score_jobs_batch(resume_text, jobs, batch_size=batch_size)
    errors = 0

    for index, (job, result) in enumerate(zip(jobs, results, strict=False), 1):
        if result["score"] == 0:
            errors += 1
        log.info(
            "[%d/%d] type=%s score=%d  %s",
            index,
            len(jobs),
            result.get("opportunity_type", "job"),
            result["score"],
            job.get("title", "?")[:60],
        )

    now = datetime.now(timezone.utc).isoformat()
    for result in results:
        conn.execute(
            "UPDATE jobs SET opportunity_type = ?, fit_score = ?, score_reasoning = ?, scored_at = ? WHERE url = ?",
            (
                result.get("opportunity_type"),
                result["score"],
                f"{result['keywords']}\n{result['reasoning']}",
                now,
                result["url"],
            ),
        )
    conn.commit()

    elapsed = time.time() - t0
    log.info(
        "Done: %d scored in %.1fs (%.1f opportunities/sec)",
        len(results),
        elapsed,
        len(results) / elapsed if elapsed > 0 else 0,
    )

    dist = conn.execute(
        """
        SELECT fit_score, COUNT(*) FROM jobs
        WHERE fit_score IS NOT NULL
        GROUP BY fit_score ORDER BY fit_score DESC
        """
    ).fetchall()
    distribution = [(row[0], row[1]) for row in dist]

    return {
        "scored": len(results),
        "errors": errors,
        "elapsed": elapsed,
        "distribution": distribution,
    }
