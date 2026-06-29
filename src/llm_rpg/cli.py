"""Rich terminal front-end and the interactive game loop."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

from .cli_menus import MenuOption, ask_menu
from .config import Config
from .engine.engine import Engine
from .game import new_game, session
from .llm.base import LLMProvider, build_provider
from .rng import seed_from_text

HELP_TEXT = """\
Type what you want to do in plain language, or use a single-key shortcut:

  [l] look around     [n] go north   [s] go south   [e] go east   [w] go west
  [i] inventory       [m] map        [h] help       [q] quit

Examples: "take the rusty key", "talk to the stranger", "attack the wolf"
"""


# Single-key in-game shortcuts -> text sent to the engine (or a slash command).
QUICK_KEYS: dict[str, str] = {
    "l": "look around",
    "i": "inventory",
    "n": "go north",
    "s": "go south",
    "e": "go east",
    "w": "go west",
    "h": "/help",
    "m": "/map",
    "q": "/quit",
}


def resolve_player_input(raw: str) -> str:
    """Expand a single-key shortcut; leave everything else unchanged."""
    key = raw.strip().lower()
    if len(key) == 1 and key in QUICK_KEYS:
        return QUICK_KEYS[key]
    return raw


class GameCLI:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.console = Console()
        self.llm: LLMProvider = build_provider(config)

    # --- Entry point ----------------------------------------------------------
    def run(self) -> None:
        self.console.print(
            Panel.fit(
                "[bold]LLM RPG[/bold]\nA world that builds itself around your choices.",
                border_style="cyan",
            )
        )
        self.console.print(f"[dim]LLM provider: {self.llm.name}[/dim]\n")
        sess = self._main_menu()
        if sess is None:
            return
        try:
            self._play(sess)
        finally:
            sess.close()

    # --- Menus ----------------------------------------------------------------
    def _main_menu(self) -> session.Session | None:
        saves = session.list_saves(self.config)
        options = [
            MenuOption("n", "New game", "new"),
        ]
        if saves:
            options.append(MenuOption("l", "Load save", "load"))
        options.append(MenuOption("q", "Quit", "quit"))

        choice = ask_menu(
            self.console,
            options,
            title="Welcome. What would you like to do?",
            default_key="n",
        )

        if choice == "quit":
            return None
        if choice == "load":
            return self._load_menu(saves)
        return self._new_game_menu()

    def _load_menu(self, saves: list[session.SaveInfo]) -> session.Session | None:
        table = Table(title="Saved games")
        table.add_column("#", justify="right")
        table.add_column("World")
        table.add_column("Genre")
        table.add_column("Turn", justify="right")
        for idx, info in enumerate(saves, 1):
            world = info.run.world_prompt
            table.add_row(
                str(idx),
                (world[:50] + "...") if len(world) > 50 else world,
                info.run.genre or "-",
                str(info.run.turn),
            )
        self.console.print(table)

        keys = [str(i) for i in range(1, len(saves) + 1)]
        idx = int(
            Prompt.ask(
                f"Load save [{ ' / '.join(keys) }]",
                choices=keys,
                default="1",
            )
        )
        return session.load_session(self.config, saves[idx - 1].path)

    def _new_game_menu(self) -> session.Session:
        self.console.print(Rule("New game"))
        mode = ask_menu(
            self.console,
            [
                MenuOption("1", "Describe your world", "describe"),
                MenuOption("2", "Pick a built-in preset", "preset"),
                MenuOption("3", "Surprise me (random)", "surprise"),
            ],
            title="How would you like to begin?",
            default_key="1",
            extra_aliases={
                "d": "describe",
                "p": "preset",
                "s": "surprise",
            },
        )

        if mode == "preset":
            names = new_game.preset_names()
            preset_options = [
                MenuOption(str(i), name, name)
                for i, name in enumerate(names, 1)
            ]
            name = ask_menu(
                self.console,
                preset_options,
                title="Choose a preset:",
                default_key="1",
            )
            world_prompt = new_game.preset_prompt(name)
        elif mode == "surprise":
            world_prompt = new_game.random_prompt()
        else:
            world_prompt = Prompt.ask(
                "Describe the world / story you want to play in"
            ).strip() or "A mysterious world waiting to be discovered."

        self.console.print(
            Panel(world_prompt, title="Your world", border_style="green")
        )

        seed = seed_from_text(world_prompt)
        sess = session.create_session(self.config, world_prompt, seed)
        with self.console.status("Seeding the world..."):
            new_game.seed_world(
                sess.repo, self.llm, sess.run, self.config.json_repair_retries
            )
        refreshed = sess.repo.get_run(sess.run.id)
        if refreshed is not None:
            sess.run = refreshed
        return sess

    # --- Play loop ------------------------------------------------------------
    def _play(self, sess: session.Session) -> None:
        engine = Engine(sess.repo, self.llm, sess.run, self.config)
        self.console.print()
        self._describe_current(engine)
        self.console.print(f"\n[dim]{HELP_TEXT}[/dim]")

        while True:
            try:
                player_text = Prompt.ask("\n[bold cyan]>[/bold cyan]").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print("\nSaving and exiting.")
                return
            if not player_text:
                continue

            player_text = resolve_player_input(player_text)
            lowered = player_text.lower()
            if lowered in {"/quit", "/exit", "quit", "exit"}:
                self.console.print("Saving and exiting.")
                return
            if lowered == "/help":
                self.console.print(Panel(HELP_TEXT, title="Help"))
                continue
            if lowered == "/map":
                self._show_map(sess)
                continue
            if lowered == "/look":
                self._describe_current(engine)
                continue

            with self.console.status("..."):
                output = engine.take_turn(player_text)
            self.console.print(f"\n{output.narration}")
            if output.player_dead:
                self.console.print(
                    Panel(
                        "[bold red]You have died.[/bold red] The story ends here.",
                        border_style="red",
                    )
                )
                return

    def _describe_current(self, engine: Engine) -> None:
        from .engine import memory

        if not engine.run.player_id:
            return
        loc_id = engine.repo.entity_location(engine.run.player_id)
        if not loc_id:
            return
        lc = memory.location_context(engine.repo, engine.run, loc_id)
        body = lc.get("description", "")
        exits = ", ".join(e["direction"] for e in lc.get("exits", [])) or "none yet"
        present = [e["name"] for e in lc.get("present_entities", [])]
        who = ("\n[dim]Here: " + ", ".join(present) + "[/dim]") if present else ""
        self.console.print(
            Panel(
                f"{body}\n\n[dim]Exits: {exits}[/dim]{who}",
                title=lc.get("name", "Here"),
                border_style="blue",
            )
        )

    def _show_map(self, sess: session.Session) -> None:
        locations = sess.repo.all_locations(sess.run.id)
        if not locations:
            self.console.print("No map yet.")
            return
        player_loc = (
            sess.repo.entity_location(sess.run.player_id)
            if sess.run.player_id
            else None
        )
        xs = [loc.x for loc in locations]
        ys = [loc.y for loc in locations]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        grid: dict[tuple[int, int], str] = {}
        for loc in locations:
            marker = "@" if loc.id == player_loc else "#"
            grid[(loc.x, loc.y)] = marker
        lines = []
        for y in range(max_y, min_y - 1, -1):
            row = "".join(grid.get((x, y), ".") for x in range(min_x, max_x + 1))
            lines.append(row)
        legend = "[dim]@ = you   # = visited   . = unknown[/dim]"
        self.console.print(
            Panel(
                "\n".join(lines) + f"\n\n{legend}",
                title="Discovered map",
                border_style="magenta",
            )
        )
