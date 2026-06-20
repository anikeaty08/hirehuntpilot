"""
Unified LLM client for hirehuntpilot.

Supported providers:
  - Anthropic
  - Groq
  - OpenAI
  - Gemini
  - Local OpenAI-compatible servers
"""

from __future__ import annotations

import logging
import os
import time

import httpx

log = logging.getLogger(__name__)

_MAX_RETRIES = 5
_TIMEOUT = 120
_RATE_LIMIT_BASE_WAIT = 10

_GEMINI_COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
_GEMINI_NATIVE_BASE = "https://generativelanguage.googleapis.com/v1beta"
_ANTHROPIC_BASE = "https://api.anthropic.com/v1"


def _detect_provider() -> tuple[str, str, str, str]:
    """Return (provider, base_url, model, api_key) from environment."""
    explicit_provider = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    model_override = os.environ.get("LLM_MODEL", "").strip()

    providers: dict[str, tuple[str, str, str]] = {
        "anthropic": (
            _ANTHROPIC_BASE,
            model_override or "claude-3-5-haiku-latest",
            os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        ),
        "groq": (
            "https://api.groq.com/openai/v1",
            model_override or "llama-3.3-70b-versatile",
            os.environ.get("GROQ_API_KEY", "").strip(),
        ),
        "openai": (
            "https://api.openai.com/v1",
            model_override or "gpt-4.1-mini",
            os.environ.get("OPENAI_API_KEY", "").strip(),
        ),
        "gemini": (
            _GEMINI_COMPAT_BASE,
            model_override or "gemini-2.0-flash",
            os.environ.get("GEMINI_API_KEY", "").strip(),
        ),
        "local": (
            (os.environ.get("LLM_URL") or "http://localhost:8080/v1").rstrip("/"),
            model_override or "local-model",
            os.environ.get("LLM_API_KEY", "").strip(),
        ),
    }

    if explicit_provider:
        if explicit_provider not in providers:
            raise RuntimeError("Unsupported LLM_PROVIDER. Choose one of: anthropic, groq, openai, gemini, local.")
        base_url, model, api_key = providers[explicit_provider]
        if explicit_provider != "local" and not api_key:
            raise RuntimeError(f"LLM_PROVIDER={explicit_provider} but its API key is missing.")
        return explicit_provider, base_url, model, api_key

    for name in ("anthropic", "groq", "openai", "gemini"):
        base_url, model, api_key = providers[name]
        if api_key:
            return name, base_url, model, api_key

    if os.environ.get("LLM_URL", "").strip():
        base_url, model, api_key = providers["local"]
        return "local", base_url, model, api_key

    raise RuntimeError(
        "No LLM provider configured. Set LLM_PROVIDER plus provider credentials, "
        "or configure one of ANTHROPIC_API_KEY, GROQ_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, or LLM_URL."
    )


def _provider_tuple_from_model_entry(entry: dict) -> tuple[str, str, str, str]:
    model_type = str(entry.get("model_type", "openai_chat"))
    model_name = str(entry.get("model_name", "")).strip()
    api_key = str(entry.get("api_key", "")).strip()
    client_args = entry.get("client_args", {}) or {}
    base_url = str(client_args.get("base_url", "")).strip()

    if model_type == "anthropic_chat":
        return "anthropic", _ANTHROPIC_BASE, model_name, api_key
    if model_type == "gemini_chat":
        return "gemini", base_url or _GEMINI_COMPAT_BASE, model_name, api_key

    lowered = base_url.lower()
    if "groq.com" in lowered:
        return "groq", base_url or "https://api.groq.com/openai/v1", model_name, api_key
    if "generativelanguage.googleapis.com" in lowered:
        return "gemini", base_url or _GEMINI_COMPAT_BASE, model_name, api_key
    if not base_url:
        return "openai", "https://api.openai.com/v1", model_name, api_key
    if any(token in lowered for token in ("localhost", "127.0.0.1", "0.0.0.0")):
        return "local", base_url, model_name, api_key
    return "openai", base_url, model_name, api_key


class LLMClient:
    """Thin LLM client supporting Anthropic, Gemini, and OpenAI-compatible APIs."""

    def __init__(self, provider: str, base_url: str, model: str, api_key: str) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._client = httpx.Client(timeout=_TIMEOUT)
        self._use_native_gemini = False
        self._is_gemini = provider == "gemini"
        self._is_anthropic = provider == "anthropic"

    def _chat_native_gemini(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        contents: list[dict] = []
        system_parts: list[dict] = []

        for msg in messages:
            role = msg["role"]
            text = msg.get("content", "")
            if role == "system":
                system_parts.append({"text": text})
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": text}]})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": text}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        url = f"{_GEMINI_NATIVE_BASE}/models/{self.model}:generateContent"
        resp = self._client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            params={"key": self.api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def _chat_anthropic(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        system_chunks = [m.get("content", "") for m in messages if m.get("role") == "system"]
        payload_messages: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            payload_messages.append(
                {
                    "role": role,
                    "content": [{"type": "text", "text": msg.get("content", "")}],
                }
            )

        payload: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": payload_messages,
        }
        if system_chunks:
            payload["system"] = "\n\n".join(chunk for chunk in system_chunks if chunk)

        resp = self._client.post(
            f"{self.base_url}/messages",
            json=payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        parts = data.get("content", [])
        text_parts = [part.get("text", "") for part in parts if part.get("type") == "text"]
        return "".join(text_parts).strip()

    def _chat_compat(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = self._client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
        if resp.status_code == 403 and self._is_gemini:
            raise _GeminiCompatForbidden(resp)

        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def chat(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 4096) -> str:
        if "qwen" in self.model.lower() and messages:
            first = messages[0]
            if first.get("role") == "user" and not first["content"].startswith("/no_think"):
                messages = [{"role": first["role"], "content": f"/no_think\n{first['content']}"}] + messages[1:]

        for attempt in range(_MAX_RETRIES):
            try:
                if self._is_anthropic:
                    return self._chat_anthropic(messages, temperature, max_tokens)
                if self._use_native_gemini:
                    return self._chat_native_gemini(messages, temperature, max_tokens)
                return self._chat_compat(messages, temperature, max_tokens)
            except _GeminiCompatForbidden:
                log.warning(
                    "Gemini compat endpoint returned 403 for model '%s'. Switching to native generateContent API.",
                    self.model,
                )
                self._use_native_gemini = True
                try:
                    return self._chat_native_gemini(messages, temperature, max_tokens)
                except httpx.HTTPStatusError as native_exc:
                    raise RuntimeError(
                        f"Both Gemini endpoints failed. Compat: 403 Forbidden. "
                        f"Native: {native_exc.response.status_code} - {native_exc.response.text[:200]}"
                    ) from native_exc
            except httpx.HTTPStatusError as exc:
                resp = exc.response
                if resp.status_code in (429, 503) and attempt < _MAX_RETRIES - 1:
                    retry_after = resp.headers.get("Retry-After") or resp.headers.get("X-RateLimit-Reset-Requests")
                    if retry_after:
                        try:
                            wait = float(retry_after)
                        except (TypeError, ValueError):
                            wait = _RATE_LIMIT_BASE_WAIT * (2**attempt)
                    else:
                        wait = min(_RATE_LIMIT_BASE_WAIT * (2**attempt), 60)
                    log.warning(
                        "LLM rate limited (HTTP %s). Waiting %ss before retry %d/%d.",
                        resp.status_code,
                        wait,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                raise
            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES - 1:
                    wait = min(_RATE_LIMIT_BASE_WAIT * (2**attempt), 60)
                    log.warning("LLM request timed out, retrying in %ss (attempt %d/%d)", wait, attempt + 1, _MAX_RETRIES)
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError("LLM request failed after all retries")

    def ask(self, prompt: str, **kwargs) -> str:
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def close(self) -> None:
        self._client.close()


class _GeminiCompatForbidden(Exception):
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"Gemini compat 403: {response.text[:200]}")


_instance: LLMClient | None = None
_instances_by_name: dict[str, LLMClient] = {}


class RoleLLMClient:
    def __init__(self, role: str) -> None:
        self.role = role

    def _resolve_candidates(self) -> list[str]:
        from hirehuntpilot.config import get_available_model_candidates

        return get_available_model_candidates(self.role)

    def chat(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 4096) -> str:
        from hirehuntpilot.config import record_model_failure, record_model_success

        candidates = self._resolve_candidates()
        last_exc: Exception | None = None
        for config_name in candidates:
            try:
                client = _get_client_for_config_name(config_name)
                response = client.chat(messages, temperature=temperature, max_tokens=max_tokens)
                record_model_success(config_name)
                return response
            except Exception as exc:
                record_model_failure(config_name, exc)
                last_exc = exc

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"No configured model candidates available for role '{self.role}'.")

    def ask(self, prompt: str, **kwargs) -> str:
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def close(self) -> None:
        return None


def get_client() -> LLMClient:
    global _instance
    if _instance is None:
        provider, base_url, model, api_key = _detect_provider()
        log.info("LLM provider: %s  model: %s", provider, model)
        _instance = LLMClient(provider, base_url, model, api_key)
    return _instance


def _get_client_for_config_name(config_name: str) -> LLMClient:
    from hirehuntpilot.config import load_model_config

    cached = _instances_by_name.get(config_name)
    if cached is not None:
        return cached

    cfg = load_model_config()
    match = None
    for item in cfg.get("model_configs", []):
        if item.get("config_name") == config_name:
            match = item
            break

    if not match:
        raise ValueError(f"Model config name '{config_name}' not found in model_config.json")

    provider, base_url, model, api_key = _provider_tuple_from_model_entry(match)
    client = LLMClient(provider, base_url, model, api_key)
    _instances_by_name[config_name] = client
    return client


def get_role_client(role: str) -> RoleLLMClient:
    return RoleLLMClient(role)


def reset_client() -> None:
    global _instance
    if _instance is not None:
        try:
            _instance.close()
        finally:
            _instance = None
    for client in _instances_by_name.values():
        try:
            client.close()
        except Exception:
            pass
    _instances_by_name.clear()
