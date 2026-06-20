"""hirehuntpilot first-time setup wizard.

Interactive flow that creates ~/.hirehuntpilot/ with:
  - resume.txt (and optionally resume.pdf)
  - profile.json
  - searches.yaml
  - .env (LLM API key)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

from hirehuntpilot.config import (
    APP_DIR,
    ENV_PATH,
    MODEL_CONFIG_PATH,
    PROFILE_PATH,
    RESUME_PATH,
    RESUME_PDF_PATH,
    SEARCH_CONFIG_PATH,
    _PACKAGE_MODEL_CONFIG,
    ensure_dirs,
)
from hirehuntpilot.secrets import delete_secret, set_secret

console = Console()

_MODEL_PRESETS: dict[str, list[str]] = {
    "anthropic": ["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest", "claude-3-7-sonnet-latest"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3-32b"],
    "openai": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
    "gemini": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
    "local": ["llama3.1:8b", "qwen2.5:7b", "local-model"],
}

_PROVIDER_CHOICES = ["anthropic", "groq", "openai", "gemini", "local"]


def _read_single_key() -> str:
    if os.name == "nt":
        import msvcrt

        first = msvcrt.getwch()
        if first in ("\x00", "\xe0"):
            second = msvcrt.getwch()
            return first + second
        return first

    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        first = sys.stdin.read(1)
        if first == "\x1b":
            second = sys.stdin.read(1)
            third = sys.stdin.read(1)
            return first + second + third
        return first
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _interactive_select(title: str, options: list[str], *, default_index: int = 0, help_text: str | None = None) -> str:
    if not options:
        raise ValueError("Selection requires at least one option.")

    if not sys.stdin.isatty() or os.environ.get("TERM") == "dumb":
        return Prompt.ask(title, choices=options, default=options[max(0, min(default_index, len(options) - 1))])

    index = max(0, min(default_index, len(options) - 1))

    while True:
        console.print()
        console.print(f"[bold bright_cyan]{title}[/bold bright_cyan]")
        if help_text:
            console.print(f"[dim]{help_text}[/dim]")
        console.print("[dim]Use Up/Down arrows, Enter to select, q to cancel.[/dim]")
        console.print()

        for i, option in enumerate(options):
            if i == index:
                console.print(f"[bold green]> {option}[/bold green]")
            else:
                console.print(f"  {option}")

        key = _read_single_key()
        if key in ("\r", "\n"):
            return options[index]
        if key.lower() == "q":
            raise typer.Exit(code=1)
        if key in ("\x00H", "\xe0H", "\x1b[A"):
            index = (index - 1) % len(options)
        elif key in ("\x00P", "\xe0P", "\x1b[B"):
            index = (index + 1) % len(options)

        console.clear()


def _step_panel(step: str, title: str, body: str, border_style: str = "bright_blue") -> Panel:
    heading = Text()
    heading.append(f"{step} ", style="bold white on blue")
    heading.append(title, style="bold bright_white")
    content = Text.assemble(heading, "\n", (body, "white"))
    return Panel(content, border_style=border_style, padding=(1, 2))


def _info_line(text: str) -> None:
    console.print(f"[cyan]i[/cyan] [dim]{text}[/dim]")


def _success_line(text: str) -> None:
    console.print(f"[green]OK[/green] {text}")


def _warn_line(text: str) -> None:
    console.print(f"[yellow]WARN[/yellow] {text}")


def _error_line(text: str) -> None:
    console.print(f"[red]ERR[/red] {text}")


def _read_env_lines() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _write_env_lines(values: dict[str, str]) -> None:
    lines = ["# hirehuntpilot configuration", ""]
    for key in sorted(values):
        if values[key] != "":
            lines.append(f"{key}={values[key]}")
    lines.append("")
    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")


def _load_profile() -> dict:
    if not PROFILE_PATH.exists():
        return {}
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_search_yaml() -> dict:
    if not SEARCH_CONFIG_PATH.exists():
        return {}
    try:
        return yaml.safe_load(SEARCH_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _summarize_queries(cfg: dict) -> str:
    queries = [item.get("query", "").strip() for item in cfg.get("queries", []) if item.get("query")]
    if not queries:
        return "no saved queries"
    preview = ", ".join(queries[:3])
    if len(queries) > 3:
        preview += f" (+{len(queries) - 3} more)"
    return preview


def _summarize_sources(cfg: dict) -> str:
    sources = [item.strip() for item in (cfg.get("sources") or cfg.get("boards") or []) if str(item).strip()]
    if not sources:
        return "default sources"
    return ", ".join(sources)


def _show_search_summary(cfg: dict | None = None) -> None:
    if cfg is None:
        cfg = _load_search_yaml()

    queries = _summarize_queries(cfg)
    sources = _summarize_sources(cfg)
    locations = [item.get("location", "").strip() for item in cfg.get("locations", []) if item.get("location")]
    location_text = ", ".join(locations[:3]) if locations else "no saved locations"
    console.print(f"[bold]Queries:[/bold] {queries}")
    console.print(f"[bold]Sources:[/bold] {sources}")
    console.print(f"[bold]Locations:[/bold] {location_text}")


def _provider_status() -> tuple[bool, str]:
    provider = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    model = (os.environ.get("LLM_MODEL") or "").strip()

    if not provider:
        return False, "Not configured"

    key_present = {
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "groq": bool(os.environ.get("GROQ_API_KEY")),
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "gemini": bool(os.environ.get("GEMINI_API_KEY")),
        "local": bool(os.environ.get("LLM_URL")),
    }.get(provider, False)

    if not key_present:
        return False, f"{provider} selected but credentials are missing"

    return True, f"{provider.capitalize()} ({model or 'default model'})"


def _preserve_env_snapshot() -> dict[str, str | None]:
    keys = (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_URL",
        "LLM_API_KEY",
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    )
    return {key: os.environ.get(key) for key in keys}


def _restore_env_snapshot(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _detect_openai_compatible_models(base_url: str, api_key: str = "") -> list[str]:
    import httpx

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    models: list[str] = []
    for item in data.get("data", []) or []:
        model_id = str(item.get("id") or "").strip()
        if model_id:
            models.append(model_id)
    return models


def _detect_provider_models(provider: str, env_values: dict[str, str], secrets: dict[str, str]) -> list[str]:
    import httpx

    if provider == "local":
        return _detect_openai_compatible_models(env_values.get("LLM_URL", ""), secrets.get("LLM_API_KEY", ""))

    if provider == "groq":
        return _detect_openai_compatible_models("https://api.groq.com/openai/v1", secrets.get("GROQ_API_KEY", ""))

    if provider == "openai":
        return _detect_openai_compatible_models("https://api.openai.com/v1", secrets.get("OPENAI_API_KEY", ""))

    if provider == "gemini":
        return _detect_openai_compatible_models("https://generativelanguage.googleapis.com/v1beta/openai", secrets.get("GEMINI_API_KEY", ""))

    if provider == "anthropic":
        headers = {
            "x-api-key": secrets.get("ANTHROPIC_API_KEY", ""),
            "anthropic-version": "2023-06-01",
        }
        try:
            resp = httpx.get("https://api.anthropic.com/v1/models", headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        models: list[str] = []
        for item in data.get("data", []) or []:
            model_id = str(item.get("id") or "").strip()
            if model_id:
                models.append(model_id)
        return models

    return []


def _verify_ai_candidate(
    provider: str,
    model: str,
    env_values: dict[str, str],
    secrets: dict[str, str],
    *,
    announce: bool = True,
) -> bool:
    from hirehuntpilot.llm import get_client, reset_client

    snapshot = _preserve_env_snapshot()
    try:
        for key, value in env_values.items():
            if value:
                os.environ[key] = value
        for key, value in secrets.items():
            if value:
                os.environ[key] = value
        os.environ["LLM_PROVIDER"] = provider
        os.environ["LLM_MODEL"] = model

        reset_client()
        reply = get_client().ask("Reply with exactly OK.", max_tokens=10, temperature=0.0).strip()
        if "OK" not in reply.upper():
            raise RuntimeError(f"Unexpected model response: {reply[:60]}")
        if announce:
            _success_line(f"{provider.capitalize()} verified successfully with model '{model}'.")
        return True
    except Exception as exc:
        if announce:
            _error_line(f"AI verification failed: {exc}")
        return False
    finally:
        reset_client()
        _restore_env_snapshot(snapshot)


def _read_resume_text() -> str:
    if not RESUME_PATH.exists():
        return ""
    return RESUME_PATH.read_text(encoding="utf-8-sig", errors="ignore")


def _extract_contact_block(resume_text: str) -> dict:
    email = ""
    phone = ""
    linkedin = ""
    github = ""
    website = ""

    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", resume_text)
    if email_match:
        email = email_match.group(0)

    phone_match = re.search(r"(\+?\d[\d\s\-()]{8,}\d)", resume_text)
    if phone_match:
        phone = re.sub(r"\s+", " ", phone_match.group(1)).strip()

    linkedin_match = re.search(r"(https?://(?:www\.)?linkedin\.com/[^\s)]+)", resume_text, re.IGNORECASE)
    if linkedin_match:
        linkedin = linkedin_match.group(1)

    github_match = re.search(r"(https?://(?:www\.)?github\.com/[^\s)]+|github\.com/[^\s)]+)", resume_text, re.IGNORECASE)
    if github_match:
        github = github_match.group(1)

    for raw_line in resume_text.splitlines():
        line = raw_line.strip()
        if not line or "@" in line:
            continue
        website_match = re.search(r"(https?://[^\s)]+|[A-Za-z0-9.-]+\.[a-z]{2,})", line)
        if not website_match:
            continue
        candidate = website_match.group(1)
        lowered = candidate.lower()
        if "linkedin.com" in lowered or "github.com" in lowered:
            continue
        if lowered.endswith(("gmail.com", "yahoo.com", "outlook.com", "hotmail.com")):
            continue
        website = candidate
        break

    return {
        "email": email,
        "phone": phone,
        "linkedin_url": linkedin,
        "github_url": github,
        "website_url": website,
        "portfolio_url": website,
    }


def _fallback_profile_from_resume(resume_text: str) -> dict:
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    cleaned_lines = [
        line for line in lines
        if line.lower() not in {"resume", "cv", "curriculum vitae"}
    ]

    name = "Candidate"
    headline = "Software Engineer"
    if cleaned_lines:
        name = cleaned_lines[0]
    if len(cleaned_lines) > 1:
        headline = cleaned_lines[1]

    if len(cleaned_lines) >= 2 and "@" in cleaned_lines[1]:
        headline = "Software Engineer"

    contact = _extract_contact_block(resume_text)

    skills = {
        "programming_languages": [],
        "frameworks": [],
        "tools": [],
    }
    known_languages = ["Python", "Java", "JavaScript", "TypeScript", "C++", "Go", "Rust"]
    known_frameworks = ["React", "Next.js", "FastAPI", "Node.js", "Django", "Flask", "PyTorch", "TensorFlow"]
    known_tools = ["Docker", "AWS", "Git", "MongoDB", "PostgreSQL", "Linux", "Hardhat", "Polygon"]
    lower_text = resume_text.lower()
    skills["programming_languages"] = [item for item in known_languages if item.lower() in lower_text]
    skills["frameworks"] = [item for item in known_frameworks if item.lower() in lower_text]
    skills["tools"] = [item for item in known_tools if item.lower() in lower_text]

    city = "Bengaluru" if "bengaluru" in lower_text or "bangalore" in lower_text or "blr" in lower_text else ""
    target_role = headline
    if "python" in lower_text and "backend" in lower_text:
        target_role = "Python Backend Engineer"
    elif "python" in lower_text:
        target_role = "Python Developer"

    return {
        "personal": {
            "full_name": name,
            "preferred_name": name.split()[0] if name else "",
            "email": contact["email"],
            "phone": contact["phone"],
            "city": city,
            "province_state": "",
            "country": "India" if "india" in lower_text else "",
            "postal_code": "",
            "address": "",
            "linkedin_url": contact["linkedin_url"],
            "github_url": contact["github_url"],
            "portfolio_url": contact["portfolio_url"],
            "website_url": contact["website_url"],
            "password": "",
        },
        "work_authorization": {
            "legally_authorized_to_work": True,
            "require_sponsorship": False,
            "work_permit_type": "",
        },
        "compensation": {
            "salary_expectation": "",
            "salary_currency": "INR",
            "salary_range_min": "",
            "salary_range_max": "",
        },
        "experience": {
            "years_of_experience_total": "",
            "education_level": "",
            "current_title": headline,
            "target_role": target_role,
        },
        "skills_boundary": skills,
        "resume_facts": {
            "preserved_companies": [],
            "preserved_projects": [],
            "preserved_school": "",
            "real_metrics": re.findall(r"\b\d+(?:\.\d+)?%|\b\d+[kKmM]?\+?", resume_text)[:8],
        },
        "eeo_voluntary": {
            "gender": "Decline to self-identify",
            "race_ethnicity": "Decline to self-identify",
            "veteran_status": "Decline to self-identify",
            "disability_status": "Decline to self-identify",
        },
        "availability": {
            "earliest_start_date": "Immediately",
        },
    }


def _llm_profile_from_resume(resume_text: str) -> dict:
    from hirehuntpilot.llm import get_client

    prompt = """Extract a structured candidate profile from this resume text.
Return ONLY valid JSON with this exact top-level shape:
{
  "personal": {
    "full_name": "", "preferred_name": "", "email": "", "phone": "", "city": "",
    "province_state": "", "country": "", "postal_code": "", "address": "",
    "linkedin_url": "", "github_url": "", "portfolio_url": "", "website_url": "", "password": ""
  },
  "work_authorization": {
    "legally_authorized_to_work": true, "require_sponsorship": false, "work_permit_type": ""
  },
  "compensation": {
    "salary_expectation": "", "salary_currency": "INR", "salary_range_min": "", "salary_range_max": ""
  },
  "experience": {
    "years_of_experience_total": "", "education_level": "", "current_title": "", "target_role": ""
  },
  "skills_boundary": {
    "programming_languages": [], "frameworks": [], "tools": []
  },
  "resume_facts": {
    "preserved_companies": [], "preserved_projects": [], "preserved_school": "", "real_metrics": []
  },
  "eeo_voluntary": {
    "gender": "Decline to self-identify", "race_ethnicity": "Decline to self-identify",
    "veteran_status": "Decline to self-identify", "disability_status": "Decline to self-identify"
  },
  "availability": {
    "earliest_start_date": "Immediately"
  }
}

Rules:
- Use only facts present in the resume.
- Leave fields blank if unknown.
- Infer a reasonable target_role from the resume headline and projects.
- Keep booleans conservative: if sponsorship/work authorization is unknown, set legally_authorized_to_work=true and require_sponsorship=false.
- Do not add markdown fences or commentary."""
    raw = get_client().chat(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": resume_text[:12000]},
        ],
        temperature=0.0,
        max_tokens=1800,
    )
    return json.loads(raw)


def _build_profile_from_resume(ai_enabled: bool) -> dict:
    resume_text = _read_resume_text()
    if not resume_text.strip():
        _error_line("Resume text is not available for profile generation.")
        raise typer.Exit(code=1)

    if ai_enabled:
        try:
            profile = _llm_profile_from_resume(resume_text)
            _success_line("Profile draft generated from your resume using the configured AI provider.")
            return profile
        except Exception as exc:
            _warn_line(f"AI profile extraction failed. Falling back to heuristic parsing. ({exc})")

    profile = _fallback_profile_from_resume(resume_text)
    _success_line("Profile draft generated from your resume with local parsing.")
    return profile


def _save_generated_profile(profile: dict) -> None:
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    _success_line(f"Profile saved to {PROFILE_PATH}")


def _generate_search_config_from_profile(profile: dict) -> None:
    personal = profile.get("personal", {})
    experience = profile.get("experience", {})
    skills = profile.get("skills_boundary", {})

    target_role = (experience.get("target_role") or experience.get("current_title") or "Software Engineer").strip()
    city = (personal.get("city") or "Remote").strip()
    lower_role = target_role.lower()

    queries = [target_role]
    if "backend" not in lower_role and any(
        keyword in lower_role for keyword in ("api", "platform", "server", "full stack", "full-stack")
    ):
        queries.append("Backend Engineer")
    if "engineer" not in lower_role and "developer" not in lower_role:
        queries.append("Software Engineer")
    if "full stack" in lower_role or "full-stack" in lower_role:
        queries.append("Full Stack Engineer")

    frameworks = [item for item in skills.get("frameworks", []) if item]
    languages = [item for item in skills.get("programming_languages", []) if item]
    if any("fastapi" == item.lower() for item in frameworks):
        queries.insert(1, "FastAPI Developer")
    if any(item.lower() == "python" for item in languages) and "python" in lower_role:
        queries.append("Python Developer")

    deduped_queries: list[str] = []
    for item in queries:
        normalized = item.strip()
        if normalized and normalized not in deduped_queries:
            deduped_queries.append(normalized)

    lines = [
        "# hirehuntpilot search configuration",
        "# Auto-generated from your resume profile.",
        "",
        "defaults:",
        "  hours_old: 72",
        "  results_per_source: 25",
        "",
        "locations:",
        f'  - location: "{city}"',
        "    remote: false",
        '  - location: "Remote"',
        "    remote: true",
        "",
        "sources:",
        "  - linkedin",
        "  - naukri",
        "  - indeed",
        "  - internshala",
        "  - unstop",
        "  - shine",
        "",
        "queries:",
    ]

    for idx, item in enumerate(deduped_queries[:4]):
        lines.append(f'  - query: "{item}"')
        lines.append(f"    tier: {1 if idx < 2 else 2}")

    SEARCH_CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _success_line(f"Search config saved to {SEARCH_CONFIG_PATH}")


def _verify_ai_setup() -> bool:
    from hirehuntpilot.config import load_env

    load_env()
    provider = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    model = (os.environ.get("LLM_MODEL") or "").strip()
    env_values = {key: os.environ.get(key, "") for key in ("LLM_PROVIDER", "LLM_MODEL", "LLM_URL")}
    secret_values = {
        key: os.environ.get(key, "")
        for key in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_API_KEY")
    }
    return _verify_ai_candidate(provider, model, env_values, secret_values)


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

def _setup_resume() -> None:
    """Prompt for resume file and copy into APP_DIR."""
    console.print(
        _step_panel(
            "Step 1",
            "Resume",
            "Point to your master resume file. Supported formats: .txt or .pdf",
            border_style="magenta",
        )
    )
    _info_line("Tip: a plain .txt resume gives the best results for scoring and tailoring.")

    while True:
        path_str = Prompt.ask("Resume file path")
        src = Path(path_str.strip().strip('"').strip("'")).expanduser().resolve()

        if not src.exists():
            _error_line(f"File not found: {src}")
            continue

        suffix = src.suffix.lower()
        if suffix not in (".txt", ".pdf"):
            _warn_line("Unsupported format. Use a .txt or .pdf file.")
            continue

        if suffix == ".txt":
            shutil.copy2(src, RESUME_PATH)
            _success_line(f"Copied to {RESUME_PATH}")
        elif suffix == ".pdf":
            shutil.copy2(src, RESUME_PDF_PATH)
            _success_line(f"Copied to {RESUME_PDF_PATH}")

            # Also ask for a plain-text version for LLM consumption
            txt_path_str = Prompt.ask(
                "Plain-text version of your resume (.txt)",
                default="",
            )
            if txt_path_str.strip():
                txt_src = Path(txt_path_str.strip().strip('"').strip("'")).expanduser().resolve()
                if txt_src.exists():
                    shutil.copy2(txt_src, RESUME_PATH)
                    _success_line(f"Copied to {RESUME_PATH}")
                else:
                    _warn_line("Plain-text file not found. Skipping .txt copy.")
        break


def configure_resume(*, replace: bool = False) -> None:
    ensure_dirs()
    if RESUME_PATH.exists() and not replace:
        _info_line(f"Resume already exists at {RESUME_PATH}. Use `hirehuntpilot init resume --replace` to overwrite it.")
        return
    _setup_resume()


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def _setup_profile() -> dict:
    """Walk through profile questions and return a nested profile dict."""
    console.print(
        _step_panel(
            "Step 2",
            "Profile",
            "Tell hirehuntpilot about yourself. This powers scoring, tailoring, and auto-fill.",
            border_style="cyan",
        )
    )

    profile: dict = {}

    # -- Personal --
    console.print("\n[bold cyan]Personal Information[/bold cyan]")
    _info_line("These details are used for scoring, tailoring, and application autofill.")
    full_name = Prompt.ask("Full name")
    profile["personal"] = {
        "full_name": full_name,
        "preferred_name": Prompt.ask("Preferred/nickname (leave blank to use first name)", default=""),
        "email": Prompt.ask("Email address"),
        "phone": Prompt.ask("Phone number", default=""),
        "city": Prompt.ask("City"),
        "province_state": Prompt.ask("Province/State (e.g. Ontario, California)", default=""),
        "country": Prompt.ask("Country"),
        "postal_code": Prompt.ask("Postal/ZIP code", default=""),
        "address": Prompt.ask("Street address (optional, used for form auto-fill)", default=""),
        "linkedin_url": Prompt.ask("LinkedIn URL", default=""),
        "github_url": Prompt.ask("GitHub URL (optional)", default=""),
        "portfolio_url": Prompt.ask("Portfolio URL (optional)", default=""),
        "website_url": Prompt.ask("Personal website URL (optional)", default=""),
        "password": Prompt.ask("Job site password (used for login walls during auto-apply)", password=True, default=""),
    }

    # -- Work Authorization --
    console.print("\n[bold cyan]Work Authorization[/bold cyan]")
    profile["work_authorization"] = {
        "legally_authorized_to_work": Confirm.ask("Are you legally authorized to work in your target country?"),
        "require_sponsorship": Confirm.ask("Will you now or in the future need sponsorship?"),
        "work_permit_type": Prompt.ask("Work permit type (e.g. Citizen, PR, Open Work Permit - leave blank if N/A)", default=""),
    }

    # -- Compensation --
    console.print("\n[bold cyan]Compensation[/bold cyan]")
    salary = Prompt.ask("Expected annual salary (number)", default="")
    salary_currency = Prompt.ask("Currency", default="USD")
    salary_range = Prompt.ask("Acceptable range (e.g. 80000-120000)", default="")
    range_parts = salary_range.split("-") if "-" in salary_range else [salary, salary]
    profile["compensation"] = {
        "salary_expectation": salary,
        "salary_currency": salary_currency,
        "salary_range_min": range_parts[0].strip(),
        "salary_range_max": range_parts[1].strip() if len(range_parts) > 1 else range_parts[0].strip(),
    }

    # -- Experience --
    console.print("\n[bold cyan]Experience[/bold cyan]")
    current_title = Prompt.ask("Current/most recent job title", default="")
    target_role = Prompt.ask("Target role (what you're applying for, e.g. 'Senior Backend Engineer')", default=current_title)
    profile["experience"] = {
        "years_of_experience_total": Prompt.ask("Years of professional experience", default=""),
        "education_level": Prompt.ask("Highest education (e.g. Bachelor's, Master's, PhD, Self-taught)", default=""),
        "current_title": current_title,
        "target_role": target_role,
    }

    # -- Skills Boundary --
    console.print("\n[bold cyan]Skills[/bold cyan] (comma-separated)")
    langs = Prompt.ask("Programming languages", default="")
    frameworks = Prompt.ask("Frameworks & libraries", default="")
    tools = Prompt.ask("Tools & platforms (e.g. Docker, AWS, Git)", default="")
    profile["skills_boundary"] = {
        "programming_languages": [s.strip() for s in langs.split(",") if s.strip()],
        "frameworks": [s.strip() for s in frameworks.split(",") if s.strip()],
        "tools": [s.strip() for s in tools.split(",") if s.strip()],
    }

    # -- Resume Facts (preserved truths for tailoring) --
    console.print("\n[bold cyan]Resume Facts[/bold cyan]")
    _info_line("These facts are preserved during resume tailoring. The AI should not rewrite them.")
    companies = Prompt.ask("Companies to always keep (comma-separated)", default="")
    projects = Prompt.ask("Projects to always keep (comma-separated)", default="")
    school = Prompt.ask("School name(s) to preserve", default="")
    metrics = Prompt.ask("Real metrics to preserve (e.g. '99.9% uptime, 50k users')", default="")
    profile["resume_facts"] = {
        "preserved_companies": [s.strip() for s in companies.split(",") if s.strip()],
        "preserved_projects": [s.strip() for s in projects.split(",") if s.strip()],
        "preserved_school": school.strip(),
        "real_metrics": [s.strip() for s in metrics.split(",") if s.strip()],
    }

    # -- EEO Voluntary (defaults) --
    profile["eeo_voluntary"] = {
        "gender": "Decline to self-identify",
        "race_ethnicity": "Decline to self-identify",
        "veteran_status": "Decline to self-identify",
        "disability_status": "Decline to self-identify",
    }

    # -- Availability --
    profile["availability"] = {
        "earliest_start_date": Prompt.ask("Earliest start date", default="Immediately"),
    }

    # Save
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    _success_line(f"Profile saved to {PROFILE_PATH}")
    return profile


def configure_profile(*, advanced: bool = False, rebuild_from_resume: bool = False) -> dict:
    ensure_dirs()
    if advanced:
        return _setup_profile()

    if not RESUME_PATH.exists():
        _error_line("Resume text is required to auto-generate the profile. Run `hirehuntpilot init resume` first.")
        raise typer.Exit(code=1)

    if PROFILE_PATH.exists() and not rebuild_from_resume:
        _info_line(
            f"Profile already exists at {PROFILE_PATH}. "
            "Use `hirehuntpilot init profile --rebuild` to regenerate it from the current resume "
            "or `hirehuntpilot init profile --advanced` for manual editing."
        )
        return _load_profile()

    ai_enabled = bool(_read_env_lines().get("LLM_PROVIDER"))
    profile = _build_profile_from_resume(ai_enabled=ai_enabled)
    _save_generated_profile(profile)
    return profile


# ---------------------------------------------------------------------------
# Search config
# ---------------------------------------------------------------------------

def _setup_searches() -> None:
    """Generate a searches.yaml from user input."""
    console.print(
        _step_panel(
            "Step 3",
            "Job Search Config",
            "Define the locations, titles, and sources you want HireHuntPilot to crawl.",
            border_style="yellow",
        )
    )

    location = Prompt.ask("Target city (e.g. 'Bengaluru', 'Remote', 'Pune')", default="Bengaluru")

    roles_raw = Prompt.ask(
        "Target job titles (comma-separated, e.g. 'Backend Engineer, Python Developer')"
    )
    roles = [r.strip() for r in roles_raw.split(",") if r.strip()]

    if not roles:
        _warn_line("No roles provided. Using a default role set.")
        roles = ["Python Developer"]

    sources_raw = Prompt.ask(
        "Job sources (comma-separated)",
        default="linkedin,naukri,indeed",
    )
    sources = [source.strip() for source in sources_raw.split(",") if source.strip()]
    if not sources:
        sources = ["linkedin", "naukri", "indeed"]

    # Build YAML content
    lines = [
        "# hirehuntpilot search configuration",
        "# Edit this file to refine your hirehunt-powered job search queries.",
        "",
        "defaults:",
        "  hours_old: 72",
        "  results_per_source: 25",
        "",
        "locations:",
        f'  - location: "{location}"',
        f"    remote: {str(location.lower() == 'remote').lower()}",
        "",
        "sources:",
        "",
        "queries:",
    ]
    for source in sources:
        lines.insert(-2, f"  - {source}")
    for i, role in enumerate(roles):
        lines.append(f'  - query: "{role}"')
        lines.append(f"    tier: {min(i + 1, 3)}")

    SEARCH_CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _success_line(f"Search config saved to {SEARCH_CONFIG_PATH}")


def configure_searches(*, profile: dict | None = None, regenerate: bool = False, advanced: bool = False) -> None:
    ensure_dirs()
    if SEARCH_CONFIG_PATH.exists() and not regenerate and not advanced:
        _info_line(
            f"Search config already exists at {SEARCH_CONFIG_PATH}. "
            "Use `hirehuntpilot search show` to inspect it or `hirehuntpilot init search --regenerate` to replace it."
        )
        return

    if advanced:
        _setup_searches()
        return

    if profile is None:
        profile = _load_profile()
        if not profile and PROFILE_PATH.exists():
            profile = _load_profile()
    if not profile:
        _error_line("Profile data is required to auto-generate searches. Run `hirehuntpilot init profile` first.")
        raise typer.Exit(code=1)

    _generate_search_config_from_profile(profile)
    _show_search_summary()


# ---------------------------------------------------------------------------
# AI Features
# ---------------------------------------------------------------------------

def _setup_ai_features() -> None:
    """Ask about AI scoring/tailoring - optional LLM configuration."""
    console.print(
        _step_panel(
            "Step 2",
            "AI Features",
            "An AI model powers job scoring, resume tailoring, and cover letters. "
            "Without it, you can still discover and enrich jobs.",
            border_style="green",
        )
    )

    if not Confirm.ask("Enable AI scoring and resume tailoring?", default=True):
        console.print("[dim]Discovery-only mode. You can configure AI later with [bold]hirehuntpilot init[/bold].[/dim]")
        return

    provider = _interactive_select(
        "Provider",
        _PROVIDER_CHOICES,
        default_index=_PROVIDER_CHOICES.index("groq"),
        help_text="Choose the provider to verify and save.",
    )

    env_values = _read_env_lines()
    env_values["LLM_PROVIDER"] = provider

    for key in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_URL", "LLM_API_KEY"):
        env_values.pop(key, None)
    for key in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "LLM_API_KEY"):
        delete_secret(key)

    secrets: dict[str, str] = {}
    detected_models: list[str] = []
    if provider == "anthropic":
        api_key = Prompt.ask("Anthropic API key").strip()
        if not api_key:
            _error_line("Anthropic API key is required when AI is enabled.")
            raise typer.Exit(code=1)
        secrets["ANTHROPIC_API_KEY"] = api_key
    elif provider == "groq":
        api_key = Prompt.ask("Groq API key").strip()
        if not api_key:
            _error_line("Groq API key is required when AI is enabled.")
            raise typer.Exit(code=1)
        secrets["GROQ_API_KEY"] = api_key
    elif provider == "openai":
        api_key = Prompt.ask("OpenAI API key").strip()
        if not api_key:
            _error_line("OpenAI API key is required when AI is enabled.")
            raise typer.Exit(code=1)
        secrets["OPENAI_API_KEY"] = api_key
    elif provider == "gemini":
        api_key = Prompt.ask("Gemini API key (from aistudio.google.com)").strip()
        if not api_key:
            _error_line("Gemini API key is required when AI is enabled.")
            raise typer.Exit(code=1)
        secrets["GEMINI_API_KEY"] = api_key
    elif provider == "local":
        env_values["LLM_URL"] = Prompt.ask("Local LLM endpoint URL", default="http://localhost:11434/v1").strip()
        if not env_values["LLM_URL"]:
            _error_line("A local model URL is required when provider is set to local.")
            raise typer.Exit(code=1)
        local_key = Prompt.ask("Local API key (optional)", default="")
        if local_key:
            secrets["LLM_API_KEY"] = local_key

    detected_models = _detect_provider_models(provider, env_values, secrets)
    probe_model = detected_models[0] if detected_models else _MODEL_PRESETS[provider][0]
    _info_line(f"Verifying {provider} access with '{probe_model}' before saving anything...")
    if not _verify_ai_candidate(provider, probe_model, env_values, secrets):
        raise typer.Exit(code=1)

    presets = detected_models or _MODEL_PRESETS[provider]
    model_text = Text()
    model_text.append(f"Available models for {provider}\n", style="bold bright_white")
    for preset in presets[:8]:
        model_text.append(f"  * {preset}\n", style="bright_cyan")
    console.print(Panel(model_text, border_style="bright_cyan", padding=(1, 2)))
    model_options = list(dict.fromkeys(presets))
    if "Custom model..." not in model_options:
        model_options.append("Custom model...")
    selected_model = _interactive_select(
        "Model",
        model_options,
        default_index=0,
        help_text="Detected from the provider when available. Choose a custom value only if needed.",
    )
    if selected_model == "Custom model...":
        model = Prompt.ask("Custom model", default=presets[0]).strip()
        if not model:
            _error_line("A model name is required.")
            raise typer.Exit(code=1)
    else:
        model = selected_model
    env_values["LLM_MODEL"] = model

    _info_line(f"Verifying final model selection '{model}'...")
    if not _verify_ai_candidate(provider, model, env_values, secrets):
        raise typer.Exit(code=1)

    env_values["LLM_PROVIDER"] = provider
    for key, value in secrets.items():
        if value:
            set_secret(key, value)
    _write_env_lines(env_values)
    _success_line(f"AI configuration saved to {ENV_PATH}")
    _info_line("Provider secrets were stored in the encrypted local secret store.")

    # Write the AgentScope model_config.json so all agents use the chosen model
    _write_model_config(provider, model)
    _success_line(f"AgentScope model config written to {MODEL_CONFIG_PATH}")


def configure_ai(*, force: bool = False) -> None:
    ensure_dirs()
    from hirehuntpilot.config import load_env

    load_env()
    configured, info = _provider_status()
    if configured and not force:
        _info_line(f"AI provider already configured: {info}. Use `hirehuntpilot init ai --force` to replace it.")
        return
    _setup_ai_features()



# ---------------------------------------------------------------------------
# Model config writer
# ---------------------------------------------------------------------------

def _write_model_config(provider: str, model: str) -> None:
    """Write the AgentScope model_config.json to APP_DIR based on wizard choices.

    The config assigns the chosen model to all agent roles dynamically. If the
    user picked a different provider per-role (advanced mode), this is handled
    by calling this function multiple times with role overrides.
    """
    import json
    import copy

    # Load the package template as a base
    if _PACKAGE_MODEL_CONFIG.exists():
        base = json.loads(_PACKAGE_MODEL_CONFIG.read_text(encoding="utf-8"))
    else:
        base = {"model_configs": [], "agent_roles": {}}

    # Build the active model entry for the chosen provider
    provider_to_type = {
        "anthropic": "anthropic_chat",
        "groq": "openai_chat",
        "openai": "openai_chat",
        "gemini": "openai_chat",
        "local": "openai_chat",
    }
    provider_to_base_url = {
        "groq": "https://api.groq.com/openai/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    }
    provider_to_key_env = {
        "anthropic": "${ANTHROPIC_API_KEY}",
        "groq": "${GROQ_API_KEY}",
        "openai": "${OPENAI_API_KEY}",
        "gemini": "${GEMINI_API_KEY}",
        "local": "${LLM_API_KEY:-ollama}",
    }

    active: dict = {
        "config_name": "default",
        "model_type": provider_to_type.get(provider, "openai_chat"),
        "model_name": model,
        "api_key": provider_to_key_env.get(provider, "${LLM_API_KEY}"),
        "client_args": {},
    }
    if provider == "local":
        active["client_args"]["base_url"] = "${LLM_URL:-http://localhost:11434/v1}"
    elif provider in provider_to_base_url:
        active["client_args"]["base_url"] = provider_to_base_url[provider]

    # Replace or prepend the 'default' entry in model_configs
    configs = base.get("model_configs", [])
    configs = [c for c in configs if c.get("config_name") != "default"]
    configs.insert(0, active)
    base["model_configs"] = configs

    # Point all agent roles to 'default'
    base["agent_roles"] = {
        "scoring": "default",
        "tailoring": "default",
        "cover_letter": "default",
        "apply_agent": "default",
        "telegram_router": "default",
    }

    MODEL_CONFIG_PATH.write_text(json.dumps(base, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Telegram setup
# ---------------------------------------------------------------------------

def _setup_telegram() -> None:
    """Configure the Telegram bot for remote pipeline control."""
    console.print(
        _step_panel(
            "Step 6",
            "Telegram Control Center",
            "Control HireHuntPilot remotely from Telegram. Send natural-language "
            "commands like 'find Python jobs in London' or 'apply to top 5 jobs'.",
            border_style="bright_cyan",
        )
    )

    if not Confirm.ask("Enable Telegram bot control?", default=False):
        console.print("[dim]Skipped. You can add it later by re-running the wizard.[/dim]")
        return

    console.print(
        "[dim]Create a bot via @BotFather on Telegram to get a token.\n"
        "Then message your bot once so it knows your chat ID.[/dim]\n"
    )

    token = Prompt.ask("Telegram Bot Token").strip()
    if not token:
        _warn_line("No token entered. Telegram bot not configured.")
        return

    chat_id = Prompt.ask(
        "Your Telegram Chat ID (optional — restricts access to only you)",
        default="",
    ).strip()
    if chat_id:
        try:
            int(chat_id)
        except ValueError:
            _warn_line("Telegram Chat ID must be numeric. Skipping chat restriction for now.")
            chat_id = ""

    from hirehuntpilot.secrets import set_secret
    set_secret("TELEGRAM_BOT_TOKEN", token)
    if chat_id:
        set_secret("TELEGRAM_CHAT_ID", chat_id)

    _success_line("Telegram bot token saved in encrypted storage.")
    _info_line("Start the bot with: hirehuntpilot telegram")


def configure_telegram(*, force: bool = False) -> None:
    ensure_dirs()
    configured, info = check_telegram()
    if configured and not force:
        _info_line(f"Telegram is already configured ({info}). Use `hirehuntpilot init telegram --force` to replace it.")
        return
    _setup_telegram()


# ---------------------------------------------------------------------------
# Auto-Apply
# ---------------------------------------------------------------------------

def _setup_auto_apply() -> None:
    """Configure the AgentScope-powered autonomous job application agent."""
    console.print(
        _step_panel(
            "Step 5",
            "Auto-Apply Agent",
            "HireHuntPilot can fill and submit job applications automatically using "
            "an AI browser agent (no Claude Code CLI required).",
            border_style="bright_green",
        )
    )

    if not Confirm.ask("Enable autonomous job applications?", default=True):
        console.print("[dim]You can apply manually using the tailored resumes hirehuntpilot generates.[/dim]")
        return

    # Check for Chrome
    try:
        from hirehuntpilot.config import get_chrome_path
        chrome = get_chrome_path()
        _success_line(f"Chrome detected: {chrome}")
    except FileNotFoundError:
        _warn_line("Chrome not found. Install Google Chrome or set the CHROME_PATH environment variable.")

    # Optional: CapSolver for paid CAPTCHA fallback
    console.print("\n[dim]The agent uses local OCR (ddddocr) for CAPTCHAs. "
                  "Optionally add CapSolver as a paid fallback.[/dim]")
    if Confirm.ask("Configure CapSolver API key? (optional)", default=False):
        capsolver_key = Prompt.ask("CapSolver API key")
        set_secret("CAPSOLVER_API_KEY", capsolver_key)
        _success_line("CapSolver key saved in encrypted storage.")
    else:
        console.print("[dim]Using local OCR only. You can add CapSolver later.[/dim]")


def configure_auto_apply() -> None:
    ensure_dirs()
    _setup_auto_apply()


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_wizard(advanced: bool = False, refresh_existing: bool = False) -> None:
    """Run the interactive setup wizard."""
    console.print()
    mode_str = "Advanced Mode" if advanced else "QuickStart Mode"
    console.print(
        Panel.fit(
            f"[bold green]hirehuntpilot Setup Wizard ({mode_str})[/bold green]\n\n"
            "This will create your configuration at:\n"
            f"  [cyan]{APP_DIR}[/cyan]\n\n"
            "You can re-run this anytime with [bold]hirehuntpilot init[/bold].",
            border_style="green",
        )
    )

    ensure_dirs()
    console.print(f"[dim]Created {APP_DIR}[/dim]\n")

    # Step 1: Resume
    if RESUME_PATH.exists() and not refresh_existing:
        _info_line(f"Keeping existing resume at {RESUME_PATH}. Use `hirehuntpilot init resume --replace` to change it.")
    else:
        _setup_resume()
    console.print()

    # Step 2: AI features (optional LLM)
    from hirehuntpilot.config import load_env

    load_env()
    ai_configured, ai_info = _provider_status()
    if ai_configured and not refresh_existing:
        _info_line(f"Keeping existing AI provider: {ai_info}. Use `hirehuntpilot init ai --force` to change it.")
    else:
        _setup_ai_features()
    console.print()

    # Step 3: Profile
    profile = _load_profile()
    if PROFILE_PATH.exists() and not refresh_existing:
        _info_line(f"Keeping existing profile at {PROFILE_PATH}. Use `hirehuntpilot init profile` to rebuild it.")
    elif advanced:
        profile = _setup_profile()
    else:
        console.print(
            _step_panel(
                "Step 3",
                "Profile Draft",
                "HireHuntPilot will create your profile from the resume you provided. "
                "This replaces the long manual form.",
                border_style="cyan",
            )
        )
        ai_enabled = bool(_read_env_lines().get("LLM_PROVIDER"))
        profile = _build_profile_from_resume(ai_enabled=ai_enabled)
        _save_generated_profile(profile)
    console.print()

    # Step 4: Search Config
    if SEARCH_CONFIG_PATH.exists() and not refresh_existing:
        _info_line(
            f"Keeping existing search config at {SEARCH_CONFIG_PATH}. "
            "Use `hirehuntpilot search show` to inspect it or `hirehuntpilot init search --regenerate` to replace it."
        )
        _show_search_summary()
    elif advanced:
        _setup_searches()
    else:
        console.print(
            _step_panel(
                "Step 4",
                "Search Config",
                "Search queries and locations are inferred from your resume profile. "
                "You can edit searches.yaml later if you want to refine them.",
                border_style="yellow",
            )
        )
        _generate_search_config_from_profile(profile)
        _show_search_summary()
    console.print()

    # Step 5: Auto-apply (AgentScope browser agent)
    if refresh_existing or not os.environ.get("CAPSOLVER_API_KEY"):
        _setup_auto_apply()
    else:
        _info_line("Auto-apply prerequisites already configured. Use `hirehuntpilot init auto-apply` to revisit them.")
    console.print()

    # Step 6: Telegram bot (optional remote control)
    tg_configured, tg_info = check_telegram()
    if tg_configured and not refresh_existing:
        _info_line(f"Keeping existing Telegram setup ({tg_info}). Use `hirehuntpilot init telegram --force` to change it.")
    else:
        _setup_telegram()
    console.print()

    # Done - show tier status
    from hirehuntpilot.config import get_tier, TIER_LABELS, TIER_COMMANDS

    tier = get_tier()

    tier_lines: list[str] = []
    for t in range(1, 4):
        label = TIER_LABELS[t]
        cmds = ", ".join(f"[bold]{c}[/bold]" for c in TIER_COMMANDS[t])
        if t <= tier:
            tier_lines.append(f"  [green]OK Tier {t} - {label}[/green]  ({cmds})")
        elif t == tier + 1:
            tier_lines.append(f"  [yellow]NEXT Tier {t} - {label}[/yellow]  ({cmds})")
        else:
            tier_lines.append(f"  [dim]LOCKED Tier {t} - {label}  ({cmds})[/dim]")

    unlock_hint = ""
    if tier == 1:
        unlock_hint = "\n[dim]To unlock Tier 2: connect an AI provider by re-running [bold]hirehuntpilot init[/bold].[/dim]"
    elif tier == 2:
        unlock_hint = "\n[dim]To unlock Tier 3: install Chrome.[/dim]"

    console.print(
        Panel.fit(
            "[bold green]Setup complete![/bold green]\n\n"
            f"[bold]Your tier: Tier {tier} - {TIER_LABELS[tier]}[/bold]\n\n"
            + "\n".join(tier_lines)
            + unlock_hint,
            border_style="bright_green",
        )
    )


def check_chrome_installed() -> bool:
    try:
        from hirehuntpilot.config import get_chrome_path
        get_chrome_path()
        return True
    except FileNotFoundError:
        return False


def check_ai_provider() -> tuple[bool, str]:
    from hirehuntpilot.config import load_env
    load_env()
    return _provider_status()


def check_telegram() -> tuple[bool, str]:
    from hirehuntpilot.secrets import load_secret_store
    secrets = load_secret_store()
    token = secrets.get("TELEGRAM_BOT_TOKEN")
    if token:
        return True, "Configured"
    return False, "Not configured (optional)"


def smart_launch() -> None:
    """Smart launch screen called when running 'hirehuntpilot' with no arguments."""
    import sys
    import json
    from hirehuntpilot.config import PROFILE_PATH, RESUME_PATH
    from hirehuntpilot.database import get_stats
    
    # Check setup status
    has_profile = PROFILE_PATH.exists()
    has_resume = RESUME_PATH.exists()
    
    # CASE 1: Fresh Install
    if not has_profile or not has_resume:
        console.print()
        console.print(
            Panel.fit(
                "[bold bright_green]🚀  HireHuntPilot  v0.4.0[/bold bright_green]\n"
                "[dim]AI-powered autonomous job application pipeline[/dim]",
                border_style="green",
                padding=(1, 2)
            )
        )
        console.print("\n  👋  Welcome! Looks like this is your first time.\n")
        console.print("  Let's get you set up in ~2 minutes.\n")
        console.print("  [bold green]❯  1. QuickStart[/bold green] (recommended) — sensible defaults, fast")
        console.print("     [bold cyan]2. Advanced[/bold cyan]   — full control over every option")
        console.print("     [dim]3. Skip[/dim]       — I'll configure manually\n")
        
        choice = Prompt.ask("  Choice [1/2/3]", choices=["1", "2", "3"], default="1")
        if choice == "1":
            run_wizard(advanced=False)
        elif choice == "2":
            run_wizard(advanced=True)
        else:
            console.print("Skipped setup. You can run setup later with [bold]hirehuntpilot init[/bold].")
        return

    # Load profile details
    try:
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        profile_name = profile.get("personal", {}).get("full_name", "Candidate")
        target_role = profile.get("experience", {}).get("target_role", "Developer")
    except Exception:
        profile_name = "Candidate"
        target_role = "Developer"

    ai_configured, ai_info = check_ai_provider()
    chrome_installed = check_chrome_installed()
    tg_configured, tg_info = check_telegram()

    # CASE 2: Setup complete but LLM missing
    if not ai_configured:
        console.print()
        console.print(
            Panel.fit(
                "[bold bright_green]🚀  HireHuntPilot  v0.4.0[/bold bright_green]",
                border_style="green",
                padding=(0, 2)
            )
        )
        console.print("\n  [bold cyan]System Check[/bold cyan] ──────────────────────────────────────────")
        console.print(f"  [green]✅[/green]  Profile              {profile_name} · {target_role}")
        console.print(f"  [red]❌[/red]  AI Provider          Not configured  ← blocks scoring/apply")
        console.print(f"  [{'green' if chrome_installed else 'red'}]"
                      f"{'✅' if chrome_installed else '❌'}[/{'green' if chrome_installed else 'red'}]  "
                      f"Chrome               {'Found' if chrome_installed else 'Not found'}")
        console.print("  ─────────────────────────────────────────────────────────────")
        console.print("  💡  [yellow]Run 'hirehuntpilot init' to connect an AI provider.[/yellow]")
        console.print("      Free options: Groq (llama-3.3-70b) · Gemini Flash")
        console.print("      Local/free:   Ollama (no API key needed)\n")
        console.print("  Available now (discovery only):")
        console.print("  [bold]1[/bold] Run discover")
        console.print("  [bold]2[/bold] Open dashboard")
        console.print("  [bold]3[/bold] Fix setup  →  [bold]hirehuntpilot init[/bold]")
        console.print("  [bold]Q[/bold] Quit\n")
        
        choice = Prompt.ask("  Choice", choices=["1", "2", "3", "q", "Q"], default="1").lower()
        if choice == "1":
            from hirehuntpilot.pipeline import run_pipeline
            run_pipeline(stages=["discover"], min_score=7)
        elif choice == "2":
            from hirehuntpilot.view import open_dashboard
            open_dashboard()
        elif choice == "3":
            run_wizard(advanced=False)
        return

    # CASE 3: Fully set up
    stats = get_stats()
    discovered = stats.get("total", 0)
    scored = stats.get("scored", 0)
    ready = stats.get("ready_to_apply", 0)
    
    # Check daemon status
    from hirehuntpilot.daemon import is_running
    daemon_pid = is_running()
    daemon_status = f"[green]Running (PID {daemon_pid})[/green]" if daemon_pid else "[dim]Not running[/dim]"

    console.print()
    console.print(
        Panel.fit(
            "[bold bright_green]🚀  HireHuntPilot  v0.4.0[/bold bright_green]",
            border_style="green",
            padding=(0, 2)
        )
    )
    console.print("\n  [bold cyan]System Check[/bold cyan] ──────────────────────────────────────────")
    console.print(f"  [green]✅[/green]  Profile              {profile_name} · {target_role}")
    console.print(f"  [green]✅[/green]  AI Provider          {ai_info}")
    console.print(f"  [green]✅[/green]  Chrome               Found")
    console.print(f"  [green]✅[/green]  AgentScope Config    model_config.json")
    console.print(f"  [{'green' if tg_configured else 'yellow'}]"
                  f"{'✅' if tg_configured else '⚠️'}[/{'green' if tg_configured else 'yellow'}]  "
                  f"Telegram Bot         {tg_info}")
    console.print(f"  [dim]ℹ️[/dim]  Background Daemon    {daemon_status}")
    console.print("  ─────────────────────────────────────────────────────────────")
    console.print(f"  📊  [bold]Pipeline[/bold]:  {discovered} discovered · {scored} scored · [green]{ready} ready to apply[/green]\n")

    console.print("  What do you want to do?")
    console.print("  [bold]1[/bold] Run full pipeline    discover → score → tailor → cover → pdf")
    console.print(f"  [bold]2[/bold] Apply to {ready} ready jobs")
    console.print("  [bold]3[/bold] Start Telegram bot   (control remotely)")
    console.print("  [bold]4[/bold] Start background daemon (keeps running in background)")
    console.print("  [bold]5[/bold] Stop background daemon")
    console.print("  [bold]6[/bold] Open dashboard")
    console.print("  [bold]7[/bold] Re-run setup")
    console.print("  [bold]Q[/bold] Quit\n")

    choice = Prompt.ask("  Choice [1-7/Q]", choices=["1", "2", "3", "4", "5", "6", "7", "q", "Q"], default="1").lower()
    
    if choice == "1":
        from hirehuntpilot.pipeline import run_pipeline
        run_pipeline(stages=["all"], min_score=7)
    elif choice == "2":
        from hirehuntpilot.apply.launcher import main as apply_main
        if ready == 0:
            console.print("[yellow]No tailored resumes ready to apply. Run pipeline first.[/yellow]")
            return
        apply_main(limit=ready, min_score=7, headless=False)
    elif choice == "3":
        from hirehuntpilot.telegram_bot import main as telegram_main
        telegram_main()
    elif choice == "4":
        from hirehuntpilot.daemon import start_daemon
        start_daemon()
    elif choice == "5":
        from hirehuntpilot.daemon import stop_daemon
        stop_daemon()
    elif choice == "6":
        from hirehuntpilot.view import open_dashboard
        open_dashboard()
    elif choice == "7":
        run_wizard(advanced=False)
