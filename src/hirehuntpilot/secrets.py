"""Local secret storage.

Windows uses DPAPI. Other platforms fall back to a plain JSON store so the
CLI remains usable instead of crashing at import time.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
from ctypes import POINTER, Structure, byref, c_char, c_wchar_p, create_string_buffer, string_at
from ctypes.wintypes import BOOL, DWORD, HLOCAL, LPWSTR

from hirehuntpilot.config import APP_DIR

log = logging.getLogger(__name__)

SECRET_PATH = APP_DIR / "secrets.json"
SECRET_ENV_KEYS = {
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "LLM_API_KEY",
    "CAPSOLVER_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
}


class DATA_BLOB(Structure):
    _fields_ = [("cbData", DWORD), ("pbData", POINTER(c_char))]


if sys.platform == "win32":
    from ctypes import WinDLL

    crypt32 = WinDLL("crypt32.dll")
    kernel32 = WinDLL("kernel32.dll")

    crypt32.CryptProtectData.argtypes = [
        POINTER(DATA_BLOB),
        LPWSTR,
        POINTER(DATA_BLOB),
        c_wchar_p,
        c_wchar_p,
        DWORD,
        POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = BOOL

    crypt32.CryptUnprotectData.argtypes = [
        POINTER(DATA_BLOB),
        POINTER(LPWSTR),
        POINTER(DATA_BLOB),
        c_wchar_p,
        c_wchar_p,
        DWORD,
        POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = BOOL

    kernel32.LocalFree.argtypes = [HLOCAL]
    kernel32.LocalFree.restype = HLOCAL
else:
    crypt32 = None
    kernel32 = None


def _blob_from_bytes(data: bytes) -> tuple[DATA_BLOB, object | None]:
    if not data:
        return DATA_BLOB(0, None), None
    buffer = create_string_buffer(data, len(data))
    blob = DATA_BLOB(len(data), buffer)
    return blob, buffer


def _protect_bytes(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data

    in_blob, in_buffer = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    if not crypt32.CryptProtectData(
        byref(in_blob),
        "hirehuntpilot",
        None,
        None,
        None,
        0,
        byref(out_blob),
    ):
        raise OSError("CryptProtectData failed")
    _ = in_buffer
    try:
        return string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def _unprotect_bytes(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data

    in_blob, in_buffer = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        byref(out_blob),
    ):
        raise OSError("CryptUnprotectData failed")
    _ = in_buffer
    try:
        return string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def load_secret_store() -> dict[str, str]:
    if not SECRET_PATH.exists():
        return {}

    raw = json.loads(SECRET_PATH.read_text(encoding="utf-8"))
    if sys.platform != "win32":
        return {str(key): str(value) for key, value in raw.items()}

    values: dict[str, str] = {}
    bad_keys: list[str] = []
    for key, encoded in raw.items():
        try:
            cipher = base64.b64decode(str(encoded).encode("ascii"))
            values[key] = _unprotect_bytes(cipher).decode("utf-8")
        except Exception as exc:
            log.warning("Could not decrypt stored secret for %s: %s", key, exc)
            bad_keys.append(key)
    if bad_keys:
        log.warning("Skipping unreadable secrets for keys: %s", ", ".join(bad_keys))
    return values


def save_secret_store(values: dict[str, str]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        SECRET_PATH.write_text(json.dumps(values, indent=2), encoding="utf-8")
        return

    payload: dict[str, str] = {}
    for key, value in values.items():
        cipher = _protect_bytes(value.encode("utf-8"))
        payload[key] = base64.b64encode(cipher).decode("ascii")
    SECRET_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def set_secret(key: str, value: str) -> None:
    values = load_secret_store()
    values[key] = value
    save_secret_store(values)


def delete_secret(key: str) -> None:
    values = load_secret_store()
    if key in values:
        values.pop(key)
        save_secret_store(values)


def export_secrets_to_env() -> None:
    for key, value in load_secret_store().items():
        os.environ[key] = value
