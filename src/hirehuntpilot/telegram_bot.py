"""Backward-compatible Telegram entrypoint wrapper."""

from hirehuntpilot.tele.bot import HireHuntTelegramBot, main

__all__ = ["HireHuntTelegramBot", "main"]


if __name__ == "__main__":
    main()
