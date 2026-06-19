"""Database exports."""

from hirehuntpilot.database.core import (
    close_connection,
    ensure_columns,
    get_connection,
    get_jobs_by_stage,
    get_stats,
    init_db,
    store_jobs,
)

__all__ = [
    "close_connection",
    "ensure_columns",
    "get_connection",
    "get_jobs_by_stage",
    "get_stats",
    "init_db",
    "store_jobs",
]
