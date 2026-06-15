from __future__ import annotations

from dataclasses import dataclass

from hirehuntpilot.config import AppConfig
from hirehuntpilot.integrations.telegram import TelegramNotifier
from hirehuntpilot.integrations.whatsapp import WhatsAppNotifier


@dataclass(slots=True)
class NotificationResult:
    channel: str
    ok: bool
    detail: str


class NotificationService:
    def __init__(self, config: AppConfig) -> None:
        self.telegram = TelegramNotifier(config.telegram.bot_token, config.telegram.chat_id)
        self.whatsapp = WhatsAppNotifier(
            config.whatsapp.account_sid,
            config.whatsapp.auth_token,
            config.whatsapp.from_number,
            config.whatsapp.to_number,
        )
        self.telegram_enabled = config.telegram.enabled
        self.whatsapp_enabled = config.whatsapp.enabled

    def send(self, text: str) -> list[NotificationResult]:
        results: list[NotificationResult] = []
        if self.telegram_enabled:
            ok, detail = self.telegram.send_message(text)
            results.append(NotificationResult(channel="telegram", ok=ok, detail=detail))
        if self.whatsapp_enabled:
            ok, detail = self.whatsapp.send_message(text)
            results.append(NotificationResult(channel="whatsapp", ok=ok, detail=detail))
        if not results:
            results.append(NotificationResult(channel="local", ok=True, detail="no remote notifier configured"))
        return results
