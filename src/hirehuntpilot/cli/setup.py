"""Setup-related CLI groups for hirehuntpilot."""

from __future__ import annotations

import typer

from hirehuntpilot.cli.shared import bootstrap, console

init_app = typer.Typer(help="Bootstrap or update specific setup domains.")
search_app = typer.Typer(help="Inspect or regenerate search configuration.")


@init_app.callback(invoke_without_command=True)
def init(
    ctx: typer.Context,
    advanced: bool = typer.Option(
        False, "--advanced", "-a", help="Run the full manual setup wizard."
    ),
    refresh_existing: bool = typer.Option(
        False,
        "--refresh-existing",
        help="Revisit existing setup items instead of keeping the current resume/profile/search/provider state.",
    ),
) -> None:
    """Run the setup wizard, but keep existing state by default."""
    if ctx.invoked_subcommand is not None:
        return

    from hirehuntpilot.wizard.init import run_wizard

    run_wizard(advanced=advanced, refresh_existing=refresh_existing)


@init_app.command("resume")
def init_resume(
    replace: bool = typer.Option(
        False,
        "--replace",
        help="Overwrite the existing resume file if one is already configured.",
    ),
) -> None:
    """Configure or replace the master resume."""
    from hirehuntpilot.wizard.init import configure_resume

    configure_resume(replace=replace)


@init_app.command("profile")
def init_profile(
    advanced: bool = typer.Option(False, "--advanced", help="Use the full manual profile form."),
    rebuild: bool = typer.Option(False, "--rebuild", help="Regenerate the profile from the current resume."),
) -> None:
    """Create or update the profile."""
    from hirehuntpilot.wizard.init import configure_profile

    configure_profile(advanced=advanced, rebuild_from_resume=rebuild)


@init_app.command("search")
def init_search(
    advanced: bool = typer.Option(False, "--advanced", help="Use the manual search-config prompt."),
    regenerate: bool = typer.Option(False, "--regenerate", help="Replace the current searches.yaml."),
) -> None:
    """Create or update search queries and sources."""
    from hirehuntpilot.wizard.init import configure_searches

    configure_searches(regenerate=regenerate, advanced=advanced)


@init_app.command("ai")
def init_ai(
    force: bool = typer.Option(False, "--force", help="Replace the current provider configuration."),
) -> None:
    """Configure the AI provider and model."""
    from hirehuntpilot.wizard.init import configure_ai

    configure_ai(force=force)


@init_app.command("telegram")
def init_telegram(
    force: bool = typer.Option(False, "--force", help="Replace the current Telegram bot configuration."),
) -> None:
    """Configure Telegram remote control."""
    from hirehuntpilot.wizard.init import configure_telegram

    configure_telegram(force=force)


@init_app.command("auto-apply")
def init_auto_apply() -> None:
    """Configure optional auto-apply extras such as CAPTCHA fallback."""
    from hirehuntpilot.wizard.init import configure_auto_apply

    configure_auto_apply()


@search_app.command("show")
def search_show() -> None:
    """Show the active search config driving discovery."""
    from hirehuntpilot.config import load_search_config
    from hirehuntpilot.wizard.init import _show_search_summary

    bootstrap()
    cfg = load_search_config()
    console.print()
    console.print("[bold bright_cyan]Active Search Plan[/bold bright_cyan]\n")
    _show_search_summary(cfg)
    console.print()


@search_app.command("regenerate")
def search_regenerate(
    advanced: bool = typer.Option(
        False, "--advanced", help="Use the manual search prompt instead of profile-based generation."
    ),
) -> None:
    """Replace searches.yaml from the current profile."""
    from hirehuntpilot.wizard.init import configure_searches

    configure_searches(regenerate=True, advanced=advanced)
