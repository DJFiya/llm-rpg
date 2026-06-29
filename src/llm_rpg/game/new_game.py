"""New-game flow: turn a world description into a seeded, playable run.

Default path: the player describes the world they want. Convenience paths: pick
a built-in preset, or roll a random 'surprise me' prompt. In all cases the LLM
seeds the opening location/player and the world then shapes itself around the
player's actions.
"""

from __future__ import annotations

from ..llm.base import LLMProvider
from ..rng import GameRNG, seed_from_text
from ..state.models import Location, Run
from ..state.repository import Repository
from ..engine import world_gen

PRESETS: dict[str, str] = {
    "fantasy": (
        "A high-fantasy realm of warring kingdoms, ancient ruins, and dormant "
        "magic. The player is a wanderer seeking their lost name."
    ),
    "cyberpunk": (
        "A rain-soaked megacity ruled by corporations, full of black-market "
        "implants and rogue AIs. The player is a freelance fixer in deep debt."
    ),
    "post-apocalyptic": (
        "A sun-scorched wasteland decades after the collapse, dotted with "
        "scavenger camps and buried vaults. The player wakes with no memory."
    ),
    "space-opera": (
        "A sprawling galaxy of feuding houses, derelict stations, and uncharted "
        "jump gates. The player captains a barely-spaceworthy ship."
    ),
    "cosmic-horror": (
        "A fog-bound coastal town where reality frays at the edges and the sea "
        "whispers. The player is an investigator who should have stayed home."
    ),
}

_RANDOM_SETTINGS = [
    "a floating archipelago of sky-islands tethered by ancient chains",
    "a city built inside the petrified corpse of a colossal beast",
    "a frostbound frontier where the sun has not risen in a generation",
    "a desert of glass where storms sing forgotten names",
    "a clockwork underworld beneath a drowned empire",
]
_RANDOM_ROLES = [
    "a disgraced cartographer chasing a rumor",
    "a debt-bound courier carrying a sealed box",
    "an amnesiac soldier on the losing side",
    "a hedge-witch exiled from their coven",
    "a salvager who found something that should not exist",
]


def preset_names() -> list[str]:
    return list(PRESETS.keys())


def preset_prompt(name: str) -> str:
    return PRESETS[name]


def random_prompt(seed_text: str | None = None) -> str:
    """Generate a 'surprise me' world prompt (deterministic if seeded)."""
    rng = GameRNG(seed_from_text(seed_text)) if seed_text else GameRNG(
        seed_from_text("surprise")
    )
    if not seed_text:
        import time

        rng = GameRNG(seed_from_text(str(time.time_ns())))
    setting = rng.choice(_RANDOM_SETTINGS)
    role = rng.choice(_RANDOM_ROLES)
    return f"A world set in {setting}. The player is {role}."


def seed_world(
    repo: Repository, llm: LLMProvider, run: Run, retries: int = 2
) -> Location:
    """Generate the opening location + player for a freshly created run."""
    return world_gen.generate_seed(repo, llm, run, retries)
