"""Shared CLI bootstrap helpers."""

from __future__ import annotations

import logging

from rich.console import Console

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

console = Console()
log = logging.getLogger(__name__)


def bootstrap() -> None:
    """Common setup: load env, create dirs, init DB."""
    from hirehuntpilot.config import ensure_dirs, load_env
    from hirehuntpilot.database import init_db

    load_env()
    ensure_dirs()
    init_db()
