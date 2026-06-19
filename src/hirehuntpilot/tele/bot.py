"""Telegram runtime wrapper around the dynamic control agent."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable

from hirehuntpilot.tele.agent import TelegramControlAgent

logger = logging.getLogger(__name__)


class HireHuntTelegramBot:
    def __init__(
        self,
        token: str,
        allowed_chat_id: int | None = None,
        model_config_name: str = "default",
    ):
        self.token = token
        self.allowed_chat_id = allowed_chat_id
        self.agent = TelegramControlAgent(model_config_name=model_config_name)
        self._pending_captcha: dict[int, asyncio.Future] = {}

    def make_captcha_alert_fn(self, chat_id: int) -> Callable:
        loop = asyncio.get_running_loop()

        async def _alert_async(message: str, screenshot_b64: str | None = None):
            import base64
            from telegram import Bot

            bot = Bot(self.token)
            await bot.send_message(chat_id=chat_id, text=f"⚠️ {message}")
            if screenshot_b64:
                img_bytes = base64.b64decode(screenshot_b64)
                await bot.send_photo(chat_id=chat_id, photo=img_bytes)
            future: asyncio.Future = loop.create_future()
            self._pending_captcha[chat_id] = future
            return await asyncio.wait_for(future, timeout=300)

        def _alert(message: str, screenshot_b64: str | None = None):
            future = asyncio.run_coroutine_threadsafe(
                _alert_async(message, screenshot_b64=screenshot_b64),
                loop,
            )
            return future.result(timeout=310)

        return _alert

    async def _process_text(self, update, text: str) -> None:
        chat_id = update.effective_chat.id
        if self.allowed_chat_id and chat_id != self.allowed_chat_id:
            await update.message.reply_text("🔒 Unauthorized.")
            return

        if chat_id in self._pending_captcha:
            future = self._pending_captcha.pop(chat_id)
            if not future.done():
                future.set_result(text)
            return

        reply = await asyncio.get_event_loop().run_in_executor(None, self.agent.handle_message, chat_id, text)
        await update.message.reply_text(reply)

    async def _handle_message(self, update, context):
        text = (update.message.text or "").strip()
        if not text:
            return
        await self._process_text(update, text)

    async def _handle_command(self, update, context):
        text = (update.message.text or "").strip()
        if not text:
            return
        if text.startswith("/"):
            command_text = text[1:]
            if not command_text or command_text in {"start", "help"}:
                command_text = "help"
            text = command_text
        await self._process_text(update, text)

    def run(self):
        from telegram.ext import Application, CommandHandler, MessageHandler, filters

        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler(["start", "help", "status"], self._handle_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        logger.info("[telegram-bot] HireHuntPilot bot starting...")
        app.run_polling(allowed_updates=["message"])


def main():
    from hirehuntpilot import config

    config.load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not set. Run 'hirehuntpilot init telegram' to configure.")
        raise SystemExit(1)

    allowed_chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "")
    allowed_chat_id = int(allowed_chat_id_str) if allowed_chat_id_str.strip() else None
    model_config_name = config.get_agent_model("telegram_router")
    bot = HireHuntTelegramBot(
        token=token,
        allowed_chat_id=allowed_chat_id,
        model_config_name=model_config_name,
    )
    bot.run()
