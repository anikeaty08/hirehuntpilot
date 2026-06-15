from __future__ import annotations


class WhatsAppNotifier:
    def __init__(self, account_sid: str, auth_token: str, from_number: str, to_number: str) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.to_number = to_number

    def enabled(self) -> bool:
        return all([self.account_sid, self.auth_token, self.from_number, self.to_number])

    def send_message(self, text: str) -> tuple[bool, str]:
        if not self.enabled():
            return False, "whatsapp not configured"
        try:
            from twilio.rest import Client
        except ImportError:
            return False, "twilio not installed"
        try:
            client = Client(self.account_sid, self.auth_token)
            client.messages.create(body=text, from_=self.from_number, to=self.to_number)
        except Exception as exc:  # pragma: no cover - external service
            return False, str(exc)
        return True, "sent"
