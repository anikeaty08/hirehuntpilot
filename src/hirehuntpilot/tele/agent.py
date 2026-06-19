"""Dynamic Telegram control agent with tool selection and chat memory."""

from __future__ import annotations

import logging
import json

from hirehuntpilot.tele.state import SessionStore
from hirehuntpilot.tele.tools import TOOLS, tool_specs

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are the Telegram control agent for HireHuntPilot.

Your job is to decide whether to:
1. reply directly for casual chat,
2. ask a brief clarifying question, or
3. choose exactly one tool to answer or act.

Rules:
- Prefer tools for factual DB/config/action requests.
- Do not invent database facts or runtime state.
- For greetings like hi/hello/hey, reply directly without a tool.
- For unclear requests, ask a short clarifying question.
- For actions, select the matching tool instead of just describing it.
- For stage execution beyond discover/apply, use the `run_stage` tool.
- When using `run_stage`, pass one of: enrich, score, tailor, cover, pdf.
- Keep replies concise.

Return valid JSON only in one of these shapes:
{"type":"reply","message":"..."}
{"type":"clarify","message":"..."}
{"type":"tool","tool":"tool_name","args":{...}}
"""


class TelegramControlAgent:
    def __init__(self, model_config_name: str):
        self.model_config_name = model_config_name
        self.sessions = SessionStore()

    def _call_model(self, messages: list[dict]) -> str:
        from hirehuntpilot.config import load_agentscope_model

        model = load_agentscope_model(self.model_config_name)
        response = model(messages)
        return (response.text or "").strip()

    def _decide(self, chat_id: int, user_message: str) -> dict:
        session = self.sessions.get(chat_id)
        tool_json = json.dumps(tool_specs(), indent=2)
        messages = [{"role": "system", "content": _SYSTEM_PROMPT + "\n\nTools:\n" + tool_json}]
        messages.extend(session.render())
        messages.append({"role": "user", "content": user_message})

        try:
            raw = self._call_model(messages).strip().strip("`").strip()
        except Exception as exc:
            logger.warning("Telegram agent model call failed: %s", exc)
            return {
                "type": "reply",
                "message": "The Telegram control model is unavailable right now. Ask for help, check AI setup, or retry once the model is configured.",
            }
        if raw.startswith("json"):
            raw = raw[4:].strip()
        try:
            return json.loads(raw)
        except Exception:
            logger.warning("Could not parse Telegram agent decision: %s", raw[:300])
            return {"type": "reply", "message": "I couldn't classify that cleanly. Ask for status, config, top jobs, or a direct action."}

    def _finalize_from_tool(self, chat_id: int, user_message: str, tool_name: str, tool_args: dict, tool_result: str) -> str:
        session = self.sessions.get(chat_id)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are summarizing a tool result for a Telegram user. "
                    "Be concise. Do not mention internal tool names unless useful. "
                    "Use the tool output faithfully and do not invent missing facts."
                ),
            }
        ]
        messages.extend(session.render())
        messages.append({"role": "user", "content": user_message})
        messages.append({"role": "assistant", "content": json.dumps({"tool": tool_name, "args": tool_args})})
        messages.append({"role": "user", "content": f"TOOL RESULT:\n{tool_result}"})
        try:
            return self._call_model(messages).strip() or tool_result
        except Exception as exc:
            logger.warning("Telegram tool summarizer failed: %s", exc)
            return tool_result

    def handle_message(self, chat_id: int, message: str) -> str:
        session = self.sessions.get(chat_id)
        decision = self._decide(chat_id, message)

        if decision.get("type") == "clarify":
            reply = decision.get("message") or "What exactly do you want me to do?"
            session.add("user", message)
            session.add("assistant", reply)
            return reply

        if decision.get("type") == "tool":
            tool_name = decision.get("tool", "")
            tool_args = decision.get("args", {}) or {}
            tool = TOOLS.get(tool_name)
            if tool is None:
                reply = f"I selected an unavailable tool: {tool_name}."
            else:
                try:
                    tool_result = tool(**tool_args)
                    reply = self._finalize_from_tool(chat_id, message, tool_name, tool_args, tool_result)
                except TypeError as exc:
                    reply = f"Tool argument mismatch for {tool_name}: {exc}"
                except Exception as exc:
                    reply = f"Tool {tool_name} failed: {exc}"
            session.add("user", message)
            session.add("assistant", reply)
            return reply

        reply = decision.get("message") or "Ask for status, top jobs, active config, or a direct action."
        session.add("user", message)
        session.add("assistant", reply)
        return reply
