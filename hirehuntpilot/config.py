from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import platform
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hirehuntpilot.compat import dump_data, load_data

try:  # pragma: no cover - optional dependency path
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:  # pragma: no cover - exercised in fallback runtime
    Fernet = None
    hashes = None
    PBKDF2HMAC = None


APP_NAME = ".hirehuntpilot"
_APP_HOME: Path | None = None


def app_home() -> Path:
    global _APP_HOME
    if _APP_HOME is not None:
        return _APP_HOME
    override = os.environ.get("HIREHUNTPILOT_HOME")
    candidates = []
    if override:
        candidates.append(Path(override))
    candidates.append(Path.home() / APP_NAME)
    candidates.append(Path.cwd() / APP_NAME)
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        _APP_HOME = candidate
        return candidate
    raise OSError("unable to determine writable app home")


def ensure_app_dirs() -> dict[str, Path]:
    root = app_home()
    directories = {
        "root": root,
        "sessions": root / "sessions",
        "resumes": root / "resumes",
        "screenshots": root / "screenshots",
        "logs": root / "logs",
    }
    for path in directories.values():
        path.mkdir(parents=True, exist_ok=True)
    return directories


@dataclass(slots=True)
class PersonalConfig:
    name: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""


@dataclass(slots=True)
class AIConfig:
    provider: str = "none"
    api_key: str = ""
    model: str = ""
    base_url: str = ""


@dataclass(slots=True)
class ResumeConfig:
    mode: str = "rendercv"
    base_pdf_path: str = ""
    json_path: str = ""
    template_id: str = ""
    rendercv_path: str = ""
    rendercv_theme: str = "classic"


@dataclass(slots=True)
class PreferencesConfig:
    role: str = ""
    cities: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    experience_min: int = 0
    experience_max: int = 0
    salary_min: int = 0
    job_type: str = "job"
    work_mode: str = "any"
    sources: list[str] = field(default_factory=lambda: ["naukri", "internshala"])
    exclude_keywords: list[str] = field(default_factory=list)
    exclude_companies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PortalCredentials:
    email: str = ""
    password: str = ""


@dataclass(slots=True)
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


@dataclass(slots=True)
class WhatsAppConfig:
    enabled: bool = False
    account_sid: str = ""
    auth_token: str = ""
    from_number: str = ""
    to_number: str = ""


@dataclass(slots=True)
class SheetsConfig:
    spreadsheet_id: str = ""
    service_account_json_path: str = ""


@dataclass(slots=True)
class RuntimeConfig:
    sqlite_path: str = str(app_home() / "runtime.db")


@dataclass(slots=True)
class AppConfig:
    personal: PersonalConfig = field(default_factory=PersonalConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    resume: ResumeConfig = field(default_factory=ResumeConfig)
    preferences: PreferencesConfig = field(default_factory=PreferencesConfig)
    portals: dict[str, PortalCredentials] = field(
        default_factory=lambda: {
            "naukri": PortalCredentials(),
            "internshala": PortalCredentials(),
        }
    )
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    sheets: SheetsConfig = field(default_factory=SheetsConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        return cls(
            personal=PersonalConfig(**data.get("personal", {})),
            ai=AIConfig(**data.get("ai", {})),
            resume=ResumeConfig(**data.get("resume", {})),
            preferences=PreferencesConfig(**data.get("preferences", {})),
            portals={
                "naukri": PortalCredentials(**data.get("portals", {}).get("naukri", {})),
                "internshala": PortalCredentials(**data.get("portals", {}).get("internshala", {})),
            },
            telegram=TelegramConfig(**data.get("telegram", {})),
            whatsapp=WhatsAppConfig(**data.get("whatsapp", {})),
            sheets=SheetsConfig(**data.get("sheets", {})),
            runtime=RuntimeConfig(**data.get("runtime", {})),
        )


class ConfigManager:
    def __init__(self, path: Path | None = None) -> None:
        dirs = ensure_app_dirs()
        self.path = path or dirs["root"] / "config.yaml"

    def default(self) -> AppConfig:
        return AppConfig()

    def load(self) -> AppConfig:
        if not self.path.exists():
            return self.default()
        payload = load_data(self.path.read_text(encoding="utf-8")) or {}
        salt = base64.urlsafe_b64decode(payload["salt"].encode("utf-8"))
        token = payload["token"].encode("utf-8")
        decrypted = self._decrypt(token, salt)
        data = load_data(decrypted.decode("utf-8")) or {}
        return AppConfig.from_dict(data)

    def save(self, config: AppConfig) -> None:
        salt = os.urandom(16)
        raw = dump_data(config.to_dict()).encode("utf-8")
        token = self._encrypt(raw, salt).decode("utf-8")
        payload = {
            "version": 1,
            "salt": base64.urlsafe_b64encode(salt).decode("utf-8"),
            "token": token,
            "backend": self.crypto_backend(),
        }
        self.path.write_text(dump_data(payload), encoding="utf-8")

    def update(self, section: str, data: dict[str, Any]) -> AppConfig:
        config = self.load()
        current = getattr(config, section)
        if hasattr(current, "__dict__"):
            for key, value in data.items():
                setattr(current, key, value)
        elif isinstance(current, dict):
            for key, value in data.items():
                current[key] = value
        else:
            setattr(config, section, data)
        self.save(config)
        return config

    def redacted_dict(self, config: AppConfig | None = None) -> dict[str, Any]:
        config = config or self.load()
        data = config.to_dict()
        sensitive = {
            ("ai", "api_key"),
            ("portals", "naukri", "password"),
            ("portals", "internshala", "password"),
            ("telegram", "bot_token"),
            ("whatsapp", "auth_token"),
            ("whatsapp", "account_sid"),
        }
        for path in sensitive:
            target: Any = data
            for key in path[:-1]:
                target = target.get(key, {})
            leaf = path[-1]
            if leaf in target and target[leaf]:
                target[leaf] = "***REDACTED***"
        return data

    def validate(self, config: AppConfig | None = None) -> list[str]:
        config = config or self.load()
        issues: list[str] = []
        if not config.personal.email:
            issues.append("personal.email is required")
        if not config.preferences.role:
            issues.append("preferences.role is required")
        if not config.resume.json_path:
            issues.append("resume.json_path is required")
        if config.resume.mode == "pdf" and not config.resume.base_pdf_path:
            issues.append("resume.base_pdf_path is required for pdf mode")
        if config.resume.mode == "rendercv" and not config.resume.rendercv_path:
            issues.append("resume.rendercv_path is required for rendercv mode")
        return issues

    def bootstrap_defaults(self) -> AppConfig:
        config = self.default()
        root = app_home()
        config.resume.json_path = str(root / "resume.json")
        config.resume.base_pdf_path = str(root / "base_resume.pdf")
        config.resume.rendercv_path = str(root / "resume_rendercv.yaml")
        config.resume.rendercv_theme = "classic"
        config.preferences.role = "python developer"
        config.preferences.cities = ["Bengaluru"]
        resume_json = Path(config.resume.json_path)
        if not resume_json.exists():
            resume_json.write_text(
                json.dumps(
                    {
                        "name": "",
                        "summary": "Entry-level software developer seeking Python-focused roles.",
                        "skills": ["python", "sql"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        self.save(config)
        return config

    def _derive_key(self, salt: bytes) -> bytes:
        machine = "|".join(
            [
                platform.system(),
                platform.machine(),
                socket.gethostname(),
                getpass.getuser(),
            ]
        )
        fingerprint = hashlib.sha256(machine.encode("utf-8")).digest()
        if PBKDF2HMAC is None:
            return hashlib.pbkdf2_hmac("sha256", fingerprint, salt, 390_000, dklen=32)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=390_000,
        )
        return base64.urlsafe_b64encode(kdf.derive(fingerprint))

    def crypto_backend(self) -> str:
        return "cryptography-fernet" if Fernet is not None else "fallback-stream"

    def _encrypt(self, raw: bytes, salt: bytes) -> bytes:
        key = self._derive_key(salt)
        if Fernet is not None:
            return Fernet(key).encrypt(raw)
        token = self._fallback_encrypt(raw, key)
        return base64.urlsafe_b64encode(token)

    def _decrypt(self, token: bytes, salt: bytes) -> bytes:
        key = self._derive_key(salt)
        if Fernet is not None:
            return Fernet(key).decrypt(token)
        decoded = base64.urlsafe_b64decode(token)
        return self._fallback_decrypt(decoded, key)

    def _fallback_encrypt(self, raw: bytes, key: bytes) -> bytes:
        nonce = os.urandom(16)
        ciphertext = self._xor_stream(raw, key, nonce)
        mac = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
        return nonce + ciphertext + mac

    def _fallback_decrypt(self, token: bytes, key: bytes) -> bytes:
        nonce = token[:16]
        mac = token[-32:]
        ciphertext = token[16:-32]
        expected = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError("config integrity check failed")
        return self._xor_stream(ciphertext, key, nonce)

    def _xor_stream(self, data: bytes, key: bytes, nonce: bytes) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < len(data):
            block = hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest()
            output.extend(block)
            counter += 1
        return bytes(a ^ b for a, b in zip(data, output[: len(data)], strict=False))
