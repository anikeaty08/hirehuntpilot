"""Telegram support package for HireHuntPilot."""

from __future__ import annotations

from hirehuntpilot.tele.agent import TelegramControlAgent

__all__ = ["TelegramControlAgent", "HireHuntTelegramBot", "main"]


def __getattr__(name: str):
    if name in {"HireHuntTelegramBot", "main"}:
        from hirehuntpilot.tele.bot import HireHuntTelegramBot, main

        return {"HireHuntTelegramBot": HireHuntTelegramBot, "main": main}[name]
    raise AttributeError(name)
