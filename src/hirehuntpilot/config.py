"""hirehuntpilot configuration: paths, platform detection, user data."""

import asyncio
import inspect
import json
import os
import platform
import shutil
from pathlib import Path

# User data directory â€” all user-specific files live here
APP_DIR = Path(os.environ.get("HIREHUNTPILOT_DIR", Path.home() / ".hirehuntpilot"))

# Core paths
DB_PATH = APP_DIR / "runtime.db"
PROFILE_PATH = APP_DIR / "profile.json"
RESUME_PATH = APP_DIR / "resume.txt"
RESUME_PDF_PATH = APP_DIR / "resume.pdf"
SEARCH_CONFIG_PATH = APP_DIR / "searches.yaml"
ENV_PATH = APP_DIR / ".env"

# Generated output
TAILORED_DIR = APP_DIR / "tailored_resumes"
COVER_LETTER_DIR = APP_DIR / "cover_letters"
LOG_DIR = APP_DIR / "logs"

# Chrome worker isolation
CHROME_WORKER_DIR = APP_DIR / "chrome-workers"
APPLY_WORKER_DIR = APP_DIR / "apply-workers"

# Package-shipped config (YAML registries)
PACKAGE_DIR = Path(__file__).parent
CONFIG_DIR = PACKAGE_DIR / "config"

# AgentScope multi-LLM model config path.
# The wizard writes the user's config here; falls back to the package template.
MODEL_CONFIG_PATH = APP_DIR / "model_config.json"
_PACKAGE_MODEL_CONFIG = CONFIG_DIR / "model_config.json"


def get_chrome_path() -> str:
    """Auto-detect Chrome/Chromium executable path, cross-platform.

    Override with CHROME_PATH environment variable.
    """
    env_path = os.environ.get("CHROME_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    system = platform.system()

    if system == "Windows":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
    elif system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    else:  # Linux
        candidates = []
        for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for c in candidates:
        if c and c.exists():
            return str(c)

    # Fall back to PATH search
    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found

    raise FileNotFoundError(
        "Chrome/Chromium not found. Install Chrome or set CHROME_PATH environment variable."
    )


def get_chrome_user_data() -> Path:
    """Default Chrome user data directory, cross-platform."""
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    else:
        return Path.home() / ".config" / "google-chrome"


def ensure_dirs():
    """Create all required directories."""
    for d in [APP_DIR, TAILORED_DIR, COVER_LETTER_DIR, LOG_DIR, CHROME_WORKER_DIR, APPLY_WORKER_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_profile() -> dict:
    """Load user profile from ~/.hirehuntpilot/profile.json."""
    import json
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"Profile not found at {PROFILE_PATH}. Run `hirehuntpilot init` first."
        )
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def load_search_config() -> dict:
    """Load search configuration from ~/.hirehuntpilot/searches.yaml."""
    import yaml
    if not SEARCH_CONFIG_PATH.exists():
        # Fall back to package-shipped example
        example = CONFIG_DIR / "searches.example.yaml"
        if example.exists():
            return yaml.safe_load(example.read_text(encoding="utf-8"))
        return {}
    return yaml.safe_load(SEARCH_CONFIG_PATH.read_text(encoding="utf-8"))


def load_sites_config() -> dict:
    """Load sites.yaml configuration (sites list, manual_ats, blocked, etc.)."""
    import yaml
    path = CONFIG_DIR / "sites.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def is_manual_ats(url: str | None) -> bool:
    """Check if a URL routes through an ATS that requires manual application."""
    if not url:
        return False
    sites_cfg = load_sites_config()
    domains = sites_cfg.get("manual_ats", [])
    url_lower = url.lower()
    return any(domain in url_lower for domain in domains)


def load_blocked_sites() -> tuple[set[str], list[str]]:
    """Load blocked sites and URL patterns from sites.yaml.

    Returns:
        (blocked_site_names, blocked_url_patterns)
    """
    cfg = load_sites_config()
    blocked = cfg.get("blocked", {})
    sites = set(blocked.get("sites", []))
    patterns = blocked.get("url_patterns", [])
    return sites, patterns


def load_blocked_sso() -> list[str]:
    """Load blocked SSO domains from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("blocked_sso", [])


def load_base_urls() -> dict[str, str | None]:
    """Load site base URLs for URL resolution from sites.yaml."""
    cfg = load_sites_config()
    return cfg.get("base_urls", {})


# ---------------------------------------------------------------------------
# Default values â€” referenced across modules instead of magic numbers
# ---------------------------------------------------------------------------

DEFAULTS = {
    "min_score": 7,
    "max_apply_attempts": 3,
    "max_tailor_attempts": 5,
    "poll_interval": 60,
    "apply_timeout": 300,
    "viewport": "1280x900",
}


def load_env():
    """Load environment variables from ~/.hirehuntpilot/.env if it exists."""
    from dotenv import load_dotenv
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    # Also try CWD .env as fallback
    load_dotenv()
    try:
        from hirehuntpilot.secrets import export_secrets_to_env
        export_secrets_to_env()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tier system â€” feature gating by installed dependencies
# ---------------------------------------------------------------------------

TIER_LABELS = {
    1: "Discovery",
    2: "AI Scoring & Tailoring",
    3: "Full Auto-Apply",
}

TIER_COMMANDS: dict[int, list[str]] = {
    1: ["init", "run discover", "run enrich", "status", "dashboard"],
    2: ["run score", "run tailor", "run cover", "run pdf", "run"],
    3: ["apply"],
}


def get_tier() -> int:
    """Detect the current tier based on available dependencies.

    Tier 1 (Discovery):            Python + pip
    Tier 2 (AI Scoring & Tailoring): + LLM API key
    Tier 3 (Full Auto-Apply):       + Chrome/Chromium
    """
    load_env()

    has_llm = any(os.environ.get(k) for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_URL", "ANTHROPIC_API_KEY", "GROQ_API_KEY"))
    if not has_llm:
        return 1

    try:
        get_chrome_path()
        has_chrome = True
    except FileNotFoundError:
        has_chrome = False

    if has_chrome:
        return 3

    return 2


def check_tier(required: int, feature: str) -> None:
    """Raise SystemExit with a clear message if the current tier is too low.

    Args:
        required: Minimum tier needed (1, 2, or 3).
        feature: Human-readable description of the feature being gated.
    """
    current = get_tier()
    if current >= required:
        return

    from rich.console import Console
    _console = Console(stderr=True)

    missing: list[str] = []
    if required >= 2 and not any(os.environ.get(k) for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_URL", "ANTHROPIC_API_KEY", "GROQ_API_KEY")):
        missing.append("LLM API key — run [bold]hirehuntpilot init[/bold]")
    if required >= 3:
        try:
            get_chrome_path()
        except FileNotFoundError:
            missing.append("Chrome/Chromium — install or set CHROME_PATH")

    _console.print(
        f"\n[red]'{feature}' requires {TIER_LABELS.get(required, f'Tier {required}')} (Tier {required}).[/red]\n"
        f"Current tier: {TIER_LABELS.get(current, f'Tier {current}')} (Tier {current})."
    )
    if missing:
        _console.print("\n[yellow]Missing:[/yellow]")
        for m in missing:
            _console.print(f"  - {m}")
    _console.print()
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# AgentScope helpers – dynamic model config loading
# ---------------------------------------------------------------------------

def load_model_config() -> dict:
    """Load the AgentScope model_config.json, resolving env-variable placeholders.

    Resolution order:
      1. ~/.hirehuntpilot/model_config.json  (written by wizard)
      2. Package-shipped template at src/hirehuntpilot/config/model_config.json

    Returns:
        Parsed dict with env-vars substituted in string values.
    """
    import json
    import re

    config_path = MODEL_CONFIG_PATH if MODEL_CONFIG_PATH.exists() else _PACKAGE_MODEL_CONFIG
    raw = config_path.read_text(encoding="utf-8")

    # Substitute ${VAR:-default} and ${VAR} patterns with env values
    def _sub(match: re.Match) -> str:
        var, _, default = match.group(1).partition(":-")
        return os.environ.get(var, default)

    raw = re.sub(r"\$\{([^}]+)\}", _sub, raw)
    return json.loads(raw)


def get_agent_model(role: str) -> str:
    """Return the AgentScope config_name for a given agent role.

    Reads the 'agent_roles' mapping from model_config.json.  If the role is
    not present, falls back to 'default'.

    Args:
        role: One of 'scoring', 'tailoring', 'cover_letter', 'apply_agent',
              'telegram_router', etc.

    Returns:
        The config_name string that maps to a model_configs entry.
    """
    cfg = load_model_config()
    roles: dict = cfg.get("agent_roles", {})
    return roles.get(role, roles.get("default", "default"))


def load_agentscope_model(config_name: str):
    """Load and instantiate an AgentScope model wrapper by its config_name.

    Args:
        config_name: Name of the config in model_config.json (e.g. 'groq', 'gemini').

    Returns:
        An instantiated ChatModelBase subclass (e.g. OpenAIChatModel).
    """
    cfg = load_model_config()
    model_configs = cfg.get("model_configs", [])

    match = None
    for item in model_configs:
        if item.get("config_name") == config_name:
            match = item
            break

    if not match:
        raise ValueError(f"Model config name '{config_name}' not found in model_config.json")

    model_type = match.get("model_type", "openai_chat")
    model_name = match.get("model_name", "")
    api_key = match.get("api_key", "")
    client_args = match.get("client_args", {}) or {}

    from agentscope.credential._factory import CredentialFactory

    cred_type_map = {
        "openai_chat": "openai_credential",
        "anthropic_chat": "anthropic_credential",
        "gemini_chat": "gemini_credential",
        "ollama_chat": "ollama_credential",
        "openai": "openai_credential",
        "anthropic": "anthropic_credential",
        "gemini": "gemini_credential",
        "ollama": "ollama_credential",
    }

    model_class_map = {
        "openai_chat": "OpenAIChatModel",
        "anthropic_chat": "AnthropicChatModel",
        "gemini_chat": "GeminiChatModel",
        "ollama_chat": "OllamaChatModel",
        "openai": "OpenAIChatModel",
        "anthropic": "AnthropicChatModel",
        "gemini": "GeminiChatModel",
        "ollama": "OllamaChatModel",
    }

    cred_type = cred_type_map.get(model_type, "openai_credential")
    class_name = model_class_map.get(model_type, "OpenAIChatModel")

    cred_data = {
        "type": cred_type,
        "api_key": api_key,
    }
    if "base_url" in client_args:
        cred_data["base_url"] = client_args["base_url"]
    if "organization" in client_args:
        cred_data["organization"] = client_args["organization"]

    credential = CredentialFactory.from_dict(cred_data)

    import agentscope.model as asm
    model_class = getattr(asm, class_name)

    kwargs = {}
    if client_args:
        clean_kwargs = {k: v for k, v in client_args.items() if k not in ("base_url", "organization")}
        if clean_kwargs:
            kwargs["client_kwargs"] = clean_kwargs

    return model_class(credential=credential, model=model_name, **kwargs)


def invoke_agentscope_model(model, messages):
    """Invoke an AgentScope model with OpenAI-style dict messages or Msg objects."""
    payload = messages
    if messages and isinstance(messages[0], dict):
        from agentscope.message import Msg
        from agentscope.message._block import TextBlock

        payload = []
        for index, message in enumerate(messages):
            role = str(message.get("role") or "user")
            name = str(message.get("name") or role or f"msg_{index}")
            content = message.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            payload.append(
                Msg(
                    name=name,
                    role=role,
                    content=[TextBlock(text=content)],
                )
            )

    response = model(payload)
    if inspect.isawaitable(response):
        response = asyncio.run(response)
    return response


