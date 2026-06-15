from __future__ import annotations


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str) -> tuple[bool, str]:
        if not self.enabled():
            return False, "telegram not configured"
        try:
            from telegram import Bot
        except ImportError:
            return False, "python-telegram-bot not installed"
        try:
            Bot(token=self.bot_token).send_message(chat_id=self.chat_id, text=text)
        except Exception as exc:  # pragma: no cover - external service
            return False, str(exc)
        return True, "sent"
