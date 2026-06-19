"""Per-chat state for Telegram control."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque


@dataclass
class ChatTurn:
    role: str
    content: str


@dataclass
class ChatSession:
    history: Deque[ChatTurn] = field(default_factory=lambda: deque(maxlen=12))

    def add(self, role: str, content: str) -> None:
        self.history.append(ChatTurn(role=role, content=content))

    def render(self) -> list[dict[str, str]]:
        return [{"role": turn.role, "content": turn.content} for turn in self.history]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[int, ChatSession] = {}

    def get(self, chat_id: int) -> ChatSession:
        if chat_id not in self._sessions:
            self._sessions[chat_id] = ChatSession()
        return self._sessions[chat_id]
