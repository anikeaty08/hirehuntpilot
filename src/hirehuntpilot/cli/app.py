"""hirehuntpilot CLI package entrypoint."""

from __future__ import annotations

from typing import Optional

import typer
from rich.prompt import Prompt
from rich.table import Table

from hirehuntpilot import __version__
from hirehuntpilot.cli.setup import init_app, search_app
from hirehuntpilot.cli.shared import bootstrap, console

app = typer.Typer(
    name="hirehuntpilot",
    help="AI-powered end-to-end job application pipeline.",
    no_args_is_help=False,
)

VALID_STAGES = ("discover", "enrich", "score", "tailor", "cover", "pdf")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]hirehuntpilot[/bold] {__version__}")
        raise typer.Exit()


app.add_typer(init_app, name="init")
app.add_typer(search_app, name="search")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """hirehuntpilot - AI-powered end-to-end job application pipeline."""
    if ctx.invoked_subcommand is None:
        import sys

        if sys.stdin.isatty():
            from hirehuntpilot.wizard.init import smart_launch

            smart_launch()
        else:
            console.print(ctx.get_help())


@app.command()
def run(
    stages: Optional[list[str]] = typer.Argument(
        None,
        help=(
            "Pipeline stages to run. "
            f"Valid: {', '.join(VALID_STAGES)}, all. "
            "Defaults to 'all' if omitted."
        ),
    ),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for tailor/cover stages."),
    workers: int = typer.Option(1, "--workers", "-w", help="Parallel threads for discovery/enrichment stages."),
    stream: bool = typer.Option(
        False, "--stream", help="Run stages concurrently with the database as a conveyor belt."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview stages without executing."),
    advanced_validation: str = typer.Option(
        "normal",
        "--advanced-validation",
        help=(
            "Validation strictness for tailor/cover stages. "
            "strict: banned words = errors, judge must pass. "
            "normal: banned words = warnings only (default, recommended for Gemini free tier). "
            "lenient: banned words ignored, LLM judge skipped (fastest, fewest API calls)."
        ),
    ),
) -> None:
    """Run pipeline stages: discover, enrich, score, tailor, cover, pdf."""
    bootstrap()

    from hirehuntpilot.pipeline import run_pipeline

    stage_list = stages if stages else ["all"]
    for stage in stage_list:
        if stage != "all" and stage not in VALID_STAGES:
            console.print(
                f"[red]Unknown stage:[/red] '{stage}'. "
                f"Valid stages: {', '.join(VALID_STAGES)}, all"
            )
            raise typer.Exit(code=1)

    llm_stages = {"score", "tailor", "cover"}
    if any(stage in stage_list for stage in llm_stages) or "all" in stage_list:
        from hirehuntpilot.config import check_tier

        check_tier(2, "AI scoring/tailoring")

    valid_modes = ("strict", "normal", "lenient")
    if advanced_validation not in valid_modes:
        console.print(
            f"[red]Invalid --advanced-validation value:[/red] '{advanced_validation}'. "
            f"Choose from: {', '.join(valid_modes)}"
        )
        raise typer.Exit(code=1)

    result = run_pipeline(
        stages=stage_list,
        min_score=min_score,
        dry_run=dry_run,
        stream=stream,
        workers=workers,
        validation_mode=advanced_validation,
    )
    if result.get("errors"):
        raise typer.Exit(code=1)


@app.command()
def apply(
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max applications to submit."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of parallel browser workers."),
    min_score: int = typer.Option(7, "--min-score", help="Minimum fit score for job selection."),
    continuous: bool = typer.Option(False, "--continuous", "-c", help="Run forever, polling for new jobs."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview actions without submitting."),
    headless: bool = typer.Option(False, "--headless", help="Run browsers in headless mode."),
    url: Optional[str] = typer.Option(None, "--url", help="Apply to a specific job URL."),
    mark_applied: Optional[str] = typer.Option(None, "--mark-applied", help="Manually mark a job URL as applied."),
    mark_failed: Optional[str] = typer.Option(
        None, "--mark-failed", help="Manually mark a job URL as failed (provide URL)."
    ),
    fail_reason: Optional[str] = typer.Option(None, "--fail-reason", help="Reason for --mark-failed."),
    reset_failed: bool = typer.Option(False, "--reset-failed", help="Reset all failed jobs for retry."),
) -> None:
    """Launch auto-apply to submit job applications."""
    bootstrap()

    from hirehuntpilot.config import PROFILE_PATH as profile_path
    from hirehuntpilot.config import check_tier
    from hirehuntpilot.database import get_connection

    if mark_applied:
        from hirehuntpilot.apply.launcher import mark_job

        mark_job(mark_applied, "applied")
        console.print(f"[green]Marked as applied:[/green] {mark_applied}")
        return

    if mark_failed:
        from hirehuntpilot.apply.launcher import mark_job

        mark_job(mark_failed, "failed", reason=fail_reason)
        console.print(f"[yellow]Marked as failed:[/yellow] {mark_failed} ({fail_reason or 'manual'})")
        return

    if reset_failed:
        from hirehuntpilot.apply.launcher import reset_failed as do_reset

        count = do_reset()
        console.print(f"[green]Reset {count} failed job(s) for retry.[/green]")
        return

    check_tier(3, "auto-apply")

    if not profile_path.exists():
        console.print(
            "[red]Profile not found.[/red]\n"
            "Run [bold]hirehuntpilot init[/bold] to create your profile first."
        )
        raise typer.Exit(code=1)

    if limit is None and not continuous and not url:
        import sys

        if sys.stdin.isatty():
            conn = get_connection()
            ready = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL AND applied_at IS NULL"
            ).fetchone()[0]
            if ready == 0:
                console.print("[yellow]No tailored resumes ready to apply. Run pipeline first.[/yellow]")
                return
            answer = Prompt.ask(
                f"Found {ready} tailored jobs ready to apply. Apply to how many? (Enter for all, 'q' to quit)",
                default="all",
            )
            if answer.lower() == "q":
                return
            if answer == "all":
                limit = ready
            else:
                try:
                    limit = int(answer)
                except ValueError:
                    limit = 1
        else:
            limit = 1
    elif limit is None:
        limit = 1

    if not url:
        conn = get_connection()
        ready = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL AND applied_at IS NULL"
        ).fetchone()[0]
        if ready == 0:
            console.print(
                "[red]No tailored resumes ready.[/red]\n"
                "Run [bold]hirehuntpilot run score tailor[/bold] first to prepare applications."
            )
            raise typer.Exit(code=1)

    from hirehuntpilot.apply.launcher import main as apply_main

    effective_limit = limit if limit is not None else (0 if continuous else 1)

    console.print("\n[bold blue]Launching Auto-Apply[/bold blue]")
    console.print(f"  Limit:    {'unlimited' if continuous else effective_limit}")
    console.print(f"  Workers:  {workers}")
    console.print(f"  Headless: {headless}")
    console.print(f"  Dry run:  {dry_run}")
    if url:
        console.print(f"  Target:   {url}")
    console.print()

    apply_main(
        limit=effective_limit,
        target_url=url,
        min_score=min_score,
        headless=headless,
        model="sonnet",
        dry_run=dry_run,
        continuous=continuous,
        workers=workers,
    )


@app.command()
def status() -> None:
    """Show pipeline statistics from the database."""
    bootstrap()

    from hirehuntpilot.config import load_search_config
    from hirehuntpilot.database import get_stats
    from hirehuntpilot.wizard.init import _summarize_queries, _summarize_sources

    stats = get_stats()
    search_cfg = load_search_config()

    console.print()
    console.print("[bold bright_cyan]HireHuntPilot Status[/bold bright_cyan]\n")

    summary = Table(title="Pipeline Overview", show_header=True, header_style="bold cyan", border_style="bright_blue")
    summary.add_column("Metric", style="bold")
    summary.add_column("Count", justify="right")

    summary.add_row("Total jobs discovered", str(stats["total"]))
    summary.add_row("With full description", str(stats["with_description"]))
    summary.add_row("Pending enrichment", str(stats["pending_detail"]))
    summary.add_row("Enrichment errors", str(stats["detail_errors"]))
    summary.add_row("Scored by LLM", str(stats["scored"]))
    summary.add_row("Pending scoring", str(stats["unscored"]))
    summary.add_row("Tailored resumes", str(stats["tailored"]))
    summary.add_row("Pending tailoring (7+)", str(stats["untailored_eligible"]))
    summary.add_row("Cover letters", str(stats["with_cover_letter"]))
    summary.add_row("Ready to apply", str(stats["ready_to_apply"]))
    summary.add_row("Applied", str(stats["applied"]))
    summary.add_row("Apply errors", str(stats["apply_errors"]))

    console.print(summary)

    if stats["score_distribution"]:
        dist_table = Table(
            title="\nScore Distribution",
            show_header=True,
            header_style="bold yellow",
            border_style="yellow",
        )
        dist_table.add_column("Score", justify="center")
        dist_table.add_column("Count", justify="right")
        dist_table.add_column("Bar")

        max_count = max(count for _, count in stats["score_distribution"]) or 1
        for score, count in stats["score_distribution"]:
            bar_len = int(count / max_count * 30)
            color = "green" if score >= 7 else "yellow" if score >= 5 else "red"
            dist_table.add_row(str(score), str(count), f"[{color}]{'=' * bar_len}[/{color}]")

        console.print(dist_table)

    if stats["by_site"]:
        site_table = Table(title="\nJobs by Source", show_header=True, header_style="bold magenta", border_style="magenta")
        site_table.add_column("Site")
        site_table.add_column("Count", justify="right")

        for site, count in stats["by_site"]:
            site_table.add_row(site or "Unknown", str(count))

        console.print(site_table)

    console.print("[bold]Active search queries:[/bold]", _summarize_queries(search_cfg))
    console.print("[bold]Active sources:[/bold]", _summarize_sources(search_cfg))
    console.print()


@app.command()
def dashboard() -> None:
    """Generate and open the HTML dashboard in your browser."""
    bootstrap()

    from hirehuntpilot.view import open_dashboard

    open_dashboard()


@app.command()
def doctor() -> None:
    """Check your setup and diagnose missing requirements."""
    import os

    from hirehuntpilot.config import (
        PROFILE_PATH,
        RESUME_PATH,
        RESUME_PDF_PATH,
        SEARCH_CONFIG_PATH,
        get_chrome_path,
        load_env,
        load_search_config,
    )
    from hirehuntpilot.secrets import load_secret_store
    from hirehuntpilot.wizard.init import _summarize_queries, _summarize_sources

    load_env()
    search_cfg = load_search_config()

    ok_mark = "[green]OK[/green]"
    fail_mark = "[red]MISSING[/red]"
    warn_mark = "[yellow]WARN[/yellow]"
    results: list[tuple[str, str, str]] = []

    if PROFILE_PATH.exists():
        results.append(("profile.json", ok_mark, str(PROFILE_PATH)))
    else:
        results.append(("profile.json", fail_mark, "Run 'hirehuntpilot init' to create"))

    if RESUME_PATH.exists():
        results.append(("resume.txt", ok_mark, str(RESUME_PATH)))
    elif RESUME_PDF_PATH.exists():
        results.append(("resume.txt", warn_mark, "Only PDF found - plain-text needed for AI stages"))
    else:
        results.append(("resume.txt", fail_mark, "Run 'hirehuntpilot init' to add your resume"))

    if SEARCH_CONFIG_PATH.exists():
        results.append(("searches.yaml", ok_mark, str(SEARCH_CONFIG_PATH)))
        results.append(("search queries", ok_mark, _summarize_queries(search_cfg)))
        results.append(("search sources", ok_mark, _summarize_sources(search_cfg)))
    else:
        results.append(("searches.yaml", warn_mark, "Will use example config - run 'hirehuntpilot init'"))

    try:
        import hirehunt  # noqa: F401

        results.append(("hirehunt", ok_mark, "hirehunt discovery package installed"))
    except ImportError:
        results.append(("hirehunt", warn_mark, "Install the hirehunt package to enable live portal discovery"))

    provider = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    model = os.environ.get("LLM_MODEL", "").strip()
    if os.environ.get("ANTHROPIC_API_KEY"):
        results.append(("AI provider", ok_mark, f"Anthropic ({model or 'claude-3-5-haiku-latest'})"))
    elif os.environ.get("GROQ_API_KEY"):
        results.append(("AI provider", ok_mark, f"Groq ({model or 'llama-3.3-70b-versatile'})"))
    elif os.environ.get("OPENAI_API_KEY"):
        results.append(("AI provider", ok_mark, f"OpenAI ({model or 'gpt-4.1-mini'})"))
    elif os.environ.get("GEMINI_API_KEY"):
        results.append(("AI provider", ok_mark, f"Gemini ({model or 'gemini-2.0-flash'})"))
    elif os.environ.get("LLM_URL"):
        local_note = model or provider or os.environ.get("LLM_URL")
        results.append(("AI provider", ok_mark, f"Local ({local_note})"))
    else:
        results.append(
            (
                "AI provider",
                fail_mark,
                "Not connected yet - run 'hirehuntpilot init' and choose Anthropic, Groq, OpenAI, Gemini, or Local",
            )
        )

    try:
        chrome_path = get_chrome_path()
        results.append(("Chrome/Chromium", ok_mark, chrome_path))
    except FileNotFoundError:
        results.append(("Chrome/Chromium", fail_mark, "Install Chrome or set CHROME_PATH env var (needed for auto-apply)"))

    try:
        import agentscope

        results.append(("AgentScope", ok_mark, f"Installed ({agentscope.__version__})"))
    except ImportError:
        results.append(("AgentScope", fail_mark, "Install agentscope package"))

    try:
        import ddddocr  # noqa: F401

        results.append(("ddddocr (local CAPTCHA)", ok_mark, "ddddocr package installed"))
    except ImportError:
        results.append(("ddddocr (local CAPTCHA)", warn_mark, "Install ddddocr package for local CAPTCHA solving"))

    secrets = load_secret_store()
    if secrets.get("TELEGRAM_BOT_TOKEN"):
        results.append(("Telegram bot control", ok_mark, "Bot token configured"))
    else:
        results.append(("Telegram bot control", "[dim]optional[/dim]", "Configure bot token in 'hirehuntpilot init' for remote control"))

    if os.environ.get("CAPSOLVER_API_KEY"):
        results.append(("CapSolver API key", ok_mark, "CAPTCHA solving enabled"))
    else:
        results.append(("CapSolver API key", "[dim]optional[/dim]", "Configure it in 'hirehuntpilot init' if you want paid CAPTCHA fallback"))

    console.print()
    console.print("[bold bright_cyan]HireHuntPilot Doctor[/bold bright_cyan]\n")

    col_w = max(len(row[0]) for row in results) + 2
    for check, status_mark, note in results:
        pad = " " * (col_w - len(check))
        console.print(f"  {check}{pad}{status_mark}  [dim]{note}[/dim]")

    console.print()

    from hirehuntpilot.config import TIER_LABELS, get_tier

    tier = get_tier()
    console.print(f"[bold]Current tier: Tier {tier} - {TIER_LABELS[tier]}[/bold]")
    if tier == 1:
        console.print("[dim]  -> Tier 2 unlocks: scoring, tailoring, cover letters (needs an AI provider)[/dim]")
        console.print("[dim]  -> Tier 3 unlocks: auto-apply (needs Chrome/Chromium)[/dim]")
    elif tier == 2:
        console.print("[dim]  -> Tier 3 unlocks: auto-apply (needs Chrome/Chromium)[/dim]")
    console.print()


@app.command("telegram")
def telegram_bot() -> None:
    """Start the Telegram bot for remote pipeline control."""
    bootstrap()
    from hirehuntpilot.telegram_bot import main as telegram_main

    telegram_main()


@app.command("start")
def start_background_daemon() -> None:
    """Start the background daemon process."""
    bootstrap()
    from hirehuntpilot.daemon import start_daemon

    start_daemon()


@app.command("stop")
def stop_background_daemon() -> None:
    """Stop the background daemon process."""
    bootstrap()
    from hirehuntpilot.daemon import stop_daemon

    stop_daemon()


def entrypoint() -> None:
    app()


if __name__ == "__main__":
    app()
