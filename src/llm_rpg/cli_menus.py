"""Shared menu helpers: numbered/letter shortcuts with clear on-screen hints."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.prompt import Prompt


@dataclass(frozen=True)
class MenuOption:
    """One row in a menu. ``key`` is the single character shown in brackets."""

    key: str
    label: str
    value: str


def print_menu(console: Console, title: str | None, options: list[MenuOption]) -> None:
    if title:
        console.print(title)
    for opt in options:
        console.print(f"  [{opt.key}] {opt.label}")


def ask_menu(
    console: Console,
    options: list[MenuOption],
    *,
    title: str | None = None,
    prompt: str = "Choose",
    default_key: str | None = None,
    extra_aliases: dict[str, str] | None = None,
) -> str:
    """Prompt until the user picks a valid option by key or alias."""
    if not options:
        raise ValueError("menu must have at least one option")

    default_key = default_key or options[0].key
    default_opt = next(o for o in options if o.key == default_key)

    lookup: dict[str, str] = {}
    for opt in options:
        lookup[opt.key.lower()] = opt.value
        lookup[opt.value.lower()] = opt.value
        # First word of label as alias (e.g. "New game" -> "new").
        first = opt.label.split()[0].lower()
        lookup[first] = opt.value

    if extra_aliases:
        lookup.update({k.lower(): v for k, v in extra_aliases.items()})

    keys_hint = " / ".join(o.key for o in options)
    print_menu(console, title, options)

    while True:
        raw = Prompt.ask(f"{prompt} [{keys_hint}]", default=default_key).strip().lower()
        if not raw:
            raw = default_key.lower()
        if raw in lookup:
            return lookup[raw]
        console.print(
            f"[yellow]Please press one of: {keys_hint}[/yellow]"
        )
