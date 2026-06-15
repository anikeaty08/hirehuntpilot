from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable


try:  # pragma: no cover - depends on optional dependency
    import typer as _typer
except ImportError:  # pragma: no cover - exercised through fallback runtime
    _typer = None

try:  # pragma: no cover - depends on optional dependency
    from rich.console import Console as _RichConsole
    from rich.table import Table as _RichTable
except ImportError:  # pragma: no cover - exercised through fallback runtime
    _RichConsole = None
    _RichTable = None

try:  # pragma: no cover - depends on optional dependency
    import yaml as _yaml
except ImportError:  # pragma: no cover - exercised through fallback runtime
    _yaml = None


def load_data(text: str) -> dict[str, Any]:
    if _yaml is not None:
        data = _yaml.safe_load(text)
        return data or {}
    return json.loads(text)


def dump_data(data: dict[str, Any]) -> str:
    if _yaml is not None:
        return _yaml.safe_dump(data, sort_keys=False)
    return json.dumps(data, indent=2)


class SimpleConsole:
    def print(self, message: Any) -> None:
        if isinstance(message, SimpleTable):
            print(message.render())
            return
        print(message)


class SimpleTable:
    def __init__(self, title: str = "") -> None:
        self.title = title
        self.columns: list[str] = []
        self.rows: list[list[str]] = []

    def add_column(self, name: str) -> None:
        self.columns.append(name)

    def add_row(self, *cells: Any) -> None:
        self.rows.append([str(cell) for cell in cells])

    def render(self) -> str:
        widths = [len(column) for column in self.columns]
        for row in self.rows:
            for idx, cell in enumerate(row):
                widths[idx] = max(widths[idx], len(cell))
        lines: list[str] = []
        if self.title:
            lines.append(self.title)
        if self.columns:
            header = " | ".join(column.ljust(widths[idx]) for idx, column in enumerate(self.columns))
            divider = "-+-".join("-" * width for width in widths)
            lines.extend([header, divider])
        for row in self.rows:
            lines.append(" | ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(row)))
        return "\n".join(lines)


def make_console():
    if _RichConsole is not None:  # pragma: no cover - depends on optional dependency
        return _RichConsole()
    return SimpleConsole()


def make_table(title: str = ""):
    if _RichTable is not None:  # pragma: no cover - depends on optional dependency
        return _RichTable(title=title)
    return SimpleTable(title=title)


def typer_available() -> bool:
    return _typer is not None


def option(default: Any, *args: Any, **kwargs: Any) -> Any:
    if _typer is None:
        return default
    return _typer.Option(default, *args, **kwargs)


class FallbackApp:
    def __init__(self, help_text: str = "") -> None:
        self.help_text = help_text
        self._commands: dict[str, Callable[..., Any]] = {}

    def command(self, name: str | None = None):
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._commands[name or func.__name__.replace("_", "-")] = func
            return func

        return decorator

    def __call__(self) -> None:
        parser = argparse.ArgumentParser(description=self.help_text)
        subparsers = parser.add_subparsers(dest="command")
        for name, func in self._commands.items():
            sub = subparsers.add_parser(name)
            sub.set_defaults(command=name)
            if name == "run":
                sub.add_argument("--limit", type=int, default=25)
            elif name == "apply":
                mode = sub.add_mutually_exclusive_group()
                mode.add_argument("--dry-run", action="store_true")
                mode.add_argument("--commit", action="store_true")
            elif name == "resume-update":
                sub.add_argument("--summary", default="")
            elif name == "telegram-relink":
                sub.add_argument("--bot-token", default="")
                sub.add_argument("--chat-id", default="")
            elif name == "sessions-refresh":
                sub.add_argument("--headed", action="store_true")
        ns = parser.parse_args()
        command = getattr(ns, "command", None)
        if not command:
            parser.print_help()
            raise SystemExit(2)
        func = self._commands[command]
        kwargs = vars(ns)
        kwargs.pop("command", None)
        if command == "apply":
            kwargs = {"dry_run": not kwargs.pop("commit")}
        elif command == "telegram-relink":
            kwargs = {"bot_token": kwargs.pop("bot_token"), "chat_id": kwargs.pop("chat_id")}
        return func(**kwargs)


def make_app(help_text: str = ""):
    if _typer is not None:  # pragma: no cover - depends on optional dependency
        return _typer.Typer(help=help_text)
    return FallbackApp(help_text=help_text)
