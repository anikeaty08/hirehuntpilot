"""BrowserApplyAgent: an AgentScope-powered ReAct agent that fills and submits
job applications using Playwright with stealth evasion and local OCR CAPTCHA
resolution.

Design principles:
- Fully dynamic: provider/model is loaded from model_config.json at runtime.
- No hardcoded selectors: the LLM observes the DOM and decides what to do.
- CAPTCHA handling: tries local ddddocr OCR first; pauses for human/Telegram
  if that fails.
- Memory: screenshot blobs are cleared every 6 turns to keep token count low,
  preserving the message log structure (equivalent to AgentScope memory marks).
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import logging
import re
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Playwright page tool functions
# ---------------------------------------------------------------------------

def _screenshot_b64(page) -> str:
    """Take a viewport screenshot and return as base64 PNG string."""
    png_bytes = page.screenshot(full_page=False, type="png")
    return base64.b64encode(png_bytes).decode()


def _get_dom_snapshot(page, max_chars: int = 8000) -> str:
    """Return truncated visible text of the page body."""
    html: str = page.evaluate("() => document.body.innerText")
    return html[:max_chars]


def _find_elements(page, selector: str) -> list[dict]:
    """Return tag/text/attrs for elements matching selector (capped at 30)."""
    results = page.query_selector_all(selector)
    out = []
    for el in results[:30]:
        try:
            tag = el.evaluate("e => e.tagName.toLowerCase()")
            text = (el.inner_text() or "")[:120]
            attrs = el.evaluate(
                "e => ({name: e.name, id: e.id, placeholder: e.placeholder, "
                "type: e.type, href: e.href})"
            )
            out.append({"tag": tag, "text": text, **attrs})
        except Exception:
            pass
    return out


def _click(page, selector: str) -> str:
    try:
        page.click(selector, timeout=8000)
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


def _fill(page, selector: str, value: str) -> str:
    try:
        page.fill(selector, value, timeout=8000)
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


def _select_option(page, selector: str, value: str) -> str:
    try:
        page.select_option(selector, value=value, timeout=8000)
        return "ok"
    except Exception:
        try:
            page.select_option(selector, label=value, timeout=8000)
            return "ok"
        except Exception as exc:
            return f"error: {exc}"


def _navigate(page, url: str) -> str:
    try:
        page.goto(url, wait_until="networkidle", timeout=20000)
        return f"navigated to {url}"
    except Exception as exc:
        return f"error: {exc}"


def _upload_file(page, selector: str, file_path: str) -> str:
    try:
        page.set_input_files(selector, file_path, timeout=8000)
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


def _scroll(page, direction: str = "down", amount: int = 500) -> str:
    delta = amount if direction == "down" else -amount
    page.evaluate(f"window.scrollBy(0, {delta})")
    return "scrolled"


def _wait(page, ms: int = 1500) -> str:
    page.wait_for_timeout(ms)
    return f"waited {ms}ms"


# ---------------------------------------------------------------------------
# Local OCR CAPTCHA solver (ddddocr)
# ---------------------------------------------------------------------------

def _solve_captcha_ocr(image_bytes: bytes) -> str | None:
    """Attempt to solve a text CAPTCHA using local ddddocr.

    Returns predicted text or None if ddddocr is unavailable/fails.
    """
    try:
        import ddddocr  # type: ignore
        ocr = ddddocr.DdddOcr(show_ad=False)
        return ocr.classification(image_bytes)
    except ImportError:
        logger.debug("ddddocr not installed, skipping local OCR")
        return None
    except Exception as exc:
        logger.warning("ddddocr OCR failed: %s", exc)
        return None


def _detect_and_solve_captcha(page) -> str:
    """Detect a CAPTCHA image on the page and attempt OCR solution.

    Returns:
        'solved:<text>'   - OCR succeeded and text was typed into nearby input
        'not_found'       - no CAPTCHA image detected
        'needs_human'     - CAPTCHA found but OCR failed
    """
    captcha_selectors = [
        "img[src*='captcha']",
        "img[alt*='captcha' i]",
        "img[id*='captcha' i]",
        "img[class*='captcha' i]",
        ".captcha img",
        "#captcha img",
    ]
    captcha_el = None
    for sel in captcha_selectors:
        el = page.query_selector(sel)
        if el:
            captcha_el = el
            break

    if captcha_el is None:
        return "not_found"

    try:
        img_bytes = captcha_el.screenshot()
    except Exception:
        return "needs_human"

    text = _solve_captcha_ocr(img_bytes)
    if not text:
        return "needs_human"

    input_selectors = [
        "input[name*='captcha' i]",
        "input[id*='captcha' i]",
        "input[placeholder*='captcha' i]",
    ]
    for sel in input_selectors:
        try:
            page.fill(sel, text, timeout=4000)
            logger.info("CAPTCHA solved via OCR: '%s'", text)
            return f"solved:{text}"
        except Exception:
            pass

    return "needs_human"


# ---------------------------------------------------------------------------
# BrowserApplyAgent
# ---------------------------------------------------------------------------

class BrowserApplyAgent:
    """ReAct-style agent that fills job application forms via Playwright.

    The agent loads its LLM dynamically from AgentScope using the config_name
    passed at construction — no provider or model is hardcoded here.

    Args:
        page: Playwright Page object (already navigated or ready to navigate).
        model_config_name: AgentScope config_name to use for reasoning.
        resume_data: Candidate info dict (name, email, phone, skills, ...).
        job_data: Job details dict (title, company, apply_url, ...).
        resume_pdf_path: Path to PDF resume for upload fields (optional).
        telegram_alert_fn: Optional callable(message, screenshot_b64) that
            sends a Telegram alert and awaits a human reply string.
        max_steps: Maximum ReAct steps before timing out.
    """

    _SYSTEM_PROMPT = """\
You are an autonomous job application agent. Fill and submit the online \
application form for the candidate below.

You operate in a ReAct loop:
  THOUGHT: reason about what to do next
  ACTION: {"action": "<name>", ...other fields...}
  OBSERVATION: the result returned

Available actions (emit exactly one ACTION: JSON line per turn):
  {"action": "screenshot"}
  {"action": "dom_snapshot"}
  {"action": "find_elements", "selector": "css-selector"}
  {"action": "click", "selector": "css-selector"}
  {"action": "fill", "selector": "css-selector", "value": "text"}
  {"action": "select_option", "selector": "css-selector", "value": "option"}
  {"action": "navigate", "url": "https://..."}
  {"action": "upload_file", "selector": "css-selector", "file_path": "/path"}
  {"action": "scroll", "direction": "down"}
  {"action": "wait"}
  {"action": "solve_captcha"}
  {"action": "done", "note": "submitted"}
  {"action": "fail", "reason": "why"}

Rules:
- Start every session with a screenshot.
- Use id/name/placeholder selectors before XPath.
- Call solve_captcha when a CAPTCHA appears.
- Call fail if you hit an SSO/account-creation wall.
- Never assume a page structure — always observe first.
"""

    def __init__(
        self,
        page,
        model_config_name: str,
        resume_data: dict,
        job_data: dict,
        resume_pdf_path: str | Path | None = None,
        telegram_alert_fn: Callable | None = None,
        max_steps: int = 40,
    ):
        self.page = page
        self.model_config_name = model_config_name
        self.resume_data = resume_data
        self.job_data = job_data
        self.resume_pdf_path = str(resume_pdf_path) if resume_pdf_path else None
        self.telegram_alert_fn = telegram_alert_fn
        self.max_steps = max_steps
        self._messages: list[dict] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_context(self) -> str:
        lines = [
            f"Job: {self.job_data.get('title', 'N/A')} at {self.job_data.get('company', 'N/A')}",
            f"Apply URL: {self.job_data.get('apply_url', 'N/A')}",
            "",
            "Candidate:",
        ]
        for k, v in self.resume_data.items():
            lines.append(f"  {k}: {v}")
        if self.resume_pdf_path:
            lines.append(f"  resume_pdf: {self.resume_pdf_path}")
        lines += [
            "",
            "Navigate to the apply URL if not already there, complete all fields,",
            "and submit. Call done when submitted or fail if blocked.",
        ]
        return "\n".join(lines)

    def _call_llm(self, messages: list[dict]) -> str:
        """Call the LLM via AgentScope using the dynamic config_name."""
        try:
            from hirehuntpilot.config import load_agentscope_model
            model = load_agentscope_model(self.model_config_name)
            response = model(messages)
            if inspect.isawaitable(response):
                response = asyncio.run(response)
            return response.text or ""
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            raise

    def _execute_action(self, action: dict) -> str:
        name = action.get("action", "")
        p = self.page

        dispatch = {
            "screenshot": lambda: f"[screenshot b64 {len(_screenshot_b64(p))} chars]",
            "dom_snapshot": lambda: _get_dom_snapshot(p),
            "find_elements": lambda: str(_find_elements(p, action.get("selector", "*"))),
            "click": lambda: _click(p, action.get("selector", "")),
            "fill": lambda: _fill(p, action.get("selector", ""), action.get("value", "")),
            "select_option": lambda: _select_option(p, action.get("selector", ""), action.get("value", "")),
            "navigate": lambda: _navigate(p, action.get("url", "")),
            "upload_file": lambda: _upload_file(p, action.get("selector", ""), action.get("file_path", "")),
            "scroll": lambda: _scroll(p, action.get("direction", "down"), action.get("amount", 500)),
            "wait": lambda: _wait(p, action.get("ms", 1500)),
            "solve_captcha": lambda: self._handle_captcha(),
        }

        if name in ("done", "fail"):
            return "__terminal__"

        fn = dispatch.get(name)
        if fn:
            return fn()
        return f"unknown action: {name}"

    def _handle_captcha(self) -> str:
        result = _detect_and_solve_captcha(self.page)
        if result != "needs_human":
            return result
        return self._escalate_captcha()

    def _escalate_captcha(self) -> str:
        if self.telegram_alert_fn:
            try:
                screenshot_b64 = _screenshot_b64(self.page)
                reply = self.telegram_alert_fn(
                    "⚠️ CAPTCHA detected! Please solve it manually, then reply 'done'.",
                    screenshot_b64=screenshot_b64,
                )
                if inspect.isawaitable(reply):
                    reply = asyncio.run(reply)
                logger.info("Captcha resolved via Telegram: %s", reply)
                return "captcha_escalated:human_resolved"
            except Exception as exc:
                logger.warning("Telegram escalation failed: %s", exc)
        logger.warning("CAPTCHA needs human intervention — no Telegram hook configured.")
        return "needs_human"

    @staticmethod
    def _parse_action(text: str) -> dict | None:
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("ACTION:"):
                json_str = line[len("ACTION:"):].strip()
                try:
                    import json
                    return json.loads(json_str)
                except Exception:
                    pass
        # Fallback: first JSON object in the text
        match = re.search(r"\{[^{}]+\}", text)
        if match:
            try:
                import json
                return json.loads(match.group())
            except Exception:
                pass
        return None

    def _clear_screenshot_blobs(self, from_index: int) -> None:
        """Replace screenshot base64 blobs with a token-efficient placeholder.

        Equivalent to an AgentScope memory mark: the message log is preserved
        but the expensive visual payload is stripped.
        """
        for msg in self._messages[from_index:]:
            if msg.get("role") == "user" and "[screenshot b64" in msg.get("content", ""):
                msg["content"] = "[screenshot cleared — token efficiency]"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict:
        """Run the ReAct loop.

        Returns:
            dict with status ('success'|'fail'|'timeout'), note, steps_taken.
        """
        self._messages = [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            {"role": "user", "content": self._build_context()},
        ]
        mark_index = 0

        for step in range(self.max_steps):
            logger.info("[apply-agent] step %d/%d", step + 1, self.max_steps)

            # Flush screenshot blobs every 6 turns to save tokens
            if step > 0 and step % 6 == 0:
                self._clear_screenshot_blobs(mark_index)
                mark_index = len(self._messages)

            try:
                response_text = self._call_llm(self._messages)
            except Exception as exc:
                return {"status": "fail", "note": f"LLM error: {exc}", "steps_taken": step}

            logger.debug("[apply-agent] LLM: %s", response_text[:400])
            self._messages.append({"role": "assistant", "content": response_text})

            action = self._parse_action(response_text)
            if action is None:
                self._messages.append({
                    "role": "user",
                    "content": (
                        "No valid ACTION: line found. "
                        "Reply with THOUGHT: ... then ACTION: {json}."
                    ),
                })
                continue

            action_name = action.get("action", "")
            logger.info("[apply-agent] action=%s", action_name)

            if action_name == "done":
                return {"status": "success", "note": action.get("note", ""), "steps_taken": step + 1}
            if action_name == "fail":
                return {"status": "fail", "note": action.get("reason", ""), "steps_taken": step + 1}

            observation = self._execute_action(action)
            self._messages.append({"role": "user", "content": f"OBSERVATION: {observation}"})

        return {"status": "timeout", "note": f"Exceeded {self.max_steps} steps", "steps_taken": self.max_steps}
