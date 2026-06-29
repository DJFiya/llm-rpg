"""CLI menu helpers and single-key shortcuts."""

from __future__ import annotations

from rich.console import Console

from llm_rpg.cli import QUICK_KEYS, resolve_player_input
from llm_rpg.cli_menus import MenuOption, ask_menu


def test_resolve_player_input_expands_single_keys():
    assert resolve_player_input("l") == "look around"
    assert resolve_player_input("n") == "go north"
    assert resolve_player_input("q") == "/quit"
    assert resolve_player_input("take key") == "take key"


def test_quick_keys_are_single_characters():
    assert all(len(k) == 1 for k in QUICK_KEYS)


def test_ask_menu_accepts_key(monkeypatch):
    console = Console(force_terminal=True, width=80)
    options = [
        MenuOption("n", "New game", "new"),
        MenuOption("q", "Quit", "quit"),
    ]
    monkeypatch.setattr("llm_rpg.cli_menus.Prompt.ask", lambda *a, **k: "q")
    assert ask_menu(console, options, default_key="n") == "quit"
