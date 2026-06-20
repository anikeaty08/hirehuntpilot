"""hirehuntpilot database layer: schema, migrations, stats, and connection helpers."""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from hirehuntpilot.config import DB_PATH

_local = threading.local()


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Get a thread-local cached SQLite connection with WAL mode enabled."""
    path = str(db_path or DB_PATH)

    if not hasattr(_local, "connections"):
        _local.connections = {}

    conn = _local.connections.get(path)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.ProgrammingError:
            pass

    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    _local.connections[path] = conn
    return conn


def close_connection(db_path: Path | str | None = None) -> None:
    """Close the cached connection for the current thread."""
    path = str(db_path or DB_PATH)
    if hasattr(_local, "connections"):
        conn = _local.connections.pop(path, None)
        if conn is not None:
            conn.close()


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create the full jobs table with all columns from every pipeline stage."""
    path = db_path or DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection(path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
    if cursor.fetchone() is not None:
        table_info = conn.execute("PRAGMA table_info(jobs)").fetchall()
        has_url = any(col[1] == "url" for col in table_info)
        if not has_url:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_name = f"jobs_legacy_backup_{timestamp}"
            logging.getLogger(__name__).warning(
                "Found incompatible 'jobs' table (missing 'url' column). Renaming it to '%s' and creating a fresh 'jobs' table.",
                backup_name,
            )
            conn.execute(f"ALTER TABLE jobs RENAME TO {backup_name}")
            conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            url                     TEXT PRIMARY KEY,
            title                   TEXT,
            salary                  TEXT,
            description             TEXT,
            location                TEXT,
            site                    TEXT,
            strategy                TEXT,
            discovered_at           TEXT,
            full_description        TEXT,
            application_url         TEXT,
            detail_scraped_at       TEXT,
            detail_error            TEXT,
            opportunity_type        TEXT,
            fit_score               INTEGER,
            score_reasoning         TEXT,
            scored_at               TEXT,
            tailored_resume_path    TEXT,
            tailored_at             TEXT,
            tailor_attempts         INTEGER DEFAULT 0,
            cover_letter_path       TEXT,
            cover_letter_at         TEXT,
            cover_attempts          INTEGER DEFAULT 0,
            applied_at              TEXT,
            apply_status            TEXT,
            apply_error             TEXT,
            apply_attempts          INTEGER DEFAULT 0,
            agent_id                TEXT,
            last_attempted_at       TEXT,
            apply_duration_ms       INTEGER,
            apply_task_id           TEXT,
            verification_confidence TEXT
        )
        """
    )
    conn.commit()
    ensure_columns(conn)
    return conn


_ALL_COLUMNS: dict[str, str] = {
    "url": "TEXT PRIMARY KEY",
    "title": "TEXT",
    "salary": "TEXT",
    "description": "TEXT",
    "location": "TEXT",
    "site": "TEXT",
    "strategy": "TEXT",
    "discovered_at": "TEXT",
    "full_description": "TEXT",
    "application_url": "TEXT",
    "detail_scraped_at": "TEXT",
    "detail_error": "TEXT",
    "opportunity_type": "TEXT",
    "fit_score": "INTEGER",
    "score_reasoning": "TEXT",
    "scored_at": "TEXT",
    "tailored_resume_path": "TEXT",
    "tailored_at": "TEXT",
    "tailor_attempts": "INTEGER DEFAULT 0",
    "cover_letter_path": "TEXT",
    "cover_letter_at": "TEXT",
    "cover_attempts": "INTEGER DEFAULT 0",
    "applied_at": "TEXT",
    "apply_status": "TEXT",
    "apply_error": "TEXT",
    "apply_attempts": "INTEGER DEFAULT 0",
    "agent_id": "TEXT",
    "last_attempted_at": "TEXT",
    "apply_duration_ms": "INTEGER",
    "apply_task_id": "TEXT",
    "verification_confidence": "TEXT",
}


def ensure_columns(conn: sqlite3.Connection | None = None) -> list[str]:
    """Add any missing columns to the jobs table."""
    if conn is None:
        conn = get_connection()

    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    added: list[str] = []
    for col, dtype in _ALL_COLUMNS.items():
        if col not in existing:
            if "PRIMARY KEY" in dtype:
                continue
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {dtype}")
            added.append(col)

    if added:
        conn.commit()
    return added


def get_stats(conn: sqlite3.Connection | None = None) -> dict:
    """Return job counts by pipeline stage."""
    if conn is None:
        conn = get_connection()

    stats: dict = {}
    stats["total"] = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    rows = conn.execute("SELECT site, COUNT(*) as cnt FROM jobs GROUP BY site ORDER BY cnt DESC").fetchall()
    stats["by_site"] = [(row[0], row[1]) for row in rows]
    stats["pending_detail"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE detail_scraped_at IS NULL").fetchone()[0]
    stats["with_description"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL").fetchone()[0]
    stats["detail_errors"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE detail_error IS NOT NULL").fetchone()[0]
    stats["scored"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL").fetchone()[0]
    stats["unscored"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL"
    ).fetchone()[0]

    dist_rows = conn.execute(
        "SELECT fit_score, COUNT(*) as cnt FROM jobs WHERE fit_score IS NOT NULL GROUP BY fit_score ORDER BY fit_score DESC"
    ).fetchall()
    stats["score_distribution"] = [(row[0], row[1]) for row in dist_rows]
    stats["tailored"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL").fetchone()[0]
    stats["untailored_eligible"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE fit_score >= 7 AND full_description IS NOT NULL AND tailored_resume_path IS NULL"
    ).fetchone()[0]
    stats["tailor_exhausted"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE COALESCE(tailor_attempts, 0) >= 5 AND tailored_resume_path IS NULL"
    ).fetchone()[0]
    stats["with_cover_letter"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE cover_letter_path IS NOT NULL"
    ).fetchone()[0]
    stats["cover_exhausted"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE COALESCE(cover_attempts, 0) >= 5 AND (cover_letter_path IS NULL OR cover_letter_path = '')"
    ).fetchone()[0]
    stats["applied"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE applied_at IS NOT NULL").fetchone()[0]
    stats["apply_errors"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE apply_error IS NOT NULL").fetchone()[0]
    stats["ready_to_apply"] = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL AND applied_at IS NULL"
    ).fetchone()[0]
    return stats


def store_jobs(conn: sqlite3.Connection, jobs: list[dict], site: str, strategy: str) -> tuple[int, int]:
    """Store discovered jobs, skipping duplicates by URL."""
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    existing = 0

    for job in jobs:
        url = job.get("url")
        if not url:
            continue
        try:
            conn.execute(
                "INSERT INTO jobs (url, title, salary, description, location, site, strategy, discovered_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    url,
                    job.get("title"),
                    job.get("salary"),
                    job.get("description"),
                    job.get("location"),
                    site,
                    strategy,
                    now,
                ),
            )
            new += 1
        except sqlite3.IntegrityError:
            existing += 1

    conn.commit()
    return new, existing


def get_jobs_by_stage(
    conn: sqlite3.Connection | None = None,
    stage: str = "discovered",
    min_score: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """Fetch jobs filtered by pipeline stage."""
    if conn is None:
        conn = get_connection()

    conditions = {
        "discovered": "1=1",
        "pending_detail": "detail_scraped_at IS NULL",
        "enriched": "full_description IS NOT NULL",
        "pending_score": "full_description IS NOT NULL AND fit_score IS NULL",
        "scored": "fit_score IS NOT NULL",
        "pending_tailor": (
            "fit_score >= ? AND full_description IS NOT NULL "
            "AND tailored_resume_path IS NULL AND COALESCE(tailor_attempts, 0) < 5"
        ),
        "tailored": "tailored_resume_path IS NOT NULL",
        "pending_apply": "tailored_resume_path IS NOT NULL AND applied_at IS NULL AND application_url IS NOT NULL",
        "applied": "applied_at IS NOT NULL",
    }

    where = conditions.get(stage, "1=1")
    params: list = []
    if "?" in where and min_score is not None:
        params.append(min_score)
    elif "?" in where:
        params.append(7)

    if min_score is not None and "fit_score" not in where and stage in ("scored", "tailored", "applied"):
        where += " AND fit_score >= ?"
        params.append(min_score)

    query = f"SELECT * FROM jobs WHERE {where} ORDER BY fit_score DESC NULLS LAST, discovered_at DESC"
    if limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(query, params).fetchall()
    if rows:
        columns = rows[0].keys()
        return [dict(zip(columns, row)) for row in rows]
    return []
