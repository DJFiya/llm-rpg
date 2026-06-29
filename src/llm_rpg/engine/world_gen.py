"""Lazy world generation: locations and entities are created only when first
encountered, then frozen as permanent, looked-up facts.

The map stays spatially consistent because every location has integer
coordinates. When the player moves in a direction we compute the destination
coordinates; if a location already occupies them we link to it instead of
creating a duplicate, and we always create the reverse exit so the graph is
bidirectionally traversable.
"""

from __future__ import annotations

import json

from ..llm.base import LLMProvider
from ..llm.prompts import (
    GENERATE_LOCATION_SYSTEM,
    GENERATE_SEED_SYSTEM,
)
from ..state.models import (
    EntityGen,
    EntityType,
    Location,
    LocationGen,
    Run,
    SeedGen,
)
from ..state.repository import Repository
from . import consistency
from .equipment import try_auto_equip

# Compass deltas on the stored coordinate grid. +y is north, +x is east.
DIRECTION_DELTAS: dict[str, tuple[int, int]] = {
    "n": (0, 1),
    "s": (0, -1),
    "e": (1, 0),
    "w": (-1, 0),
    "ne": (1, 1),
    "nw": (-1, 1),
    "se": (1, -1),
    "sw": (-1, -1),
}

OPPOSITE: dict[str, str] = {
    "n": "s",
    "s": "n",
    "e": "w",
    "w": "e",
    "ne": "sw",
    "sw": "ne",
    "nw": "se",
    "se": "nw",
}

DIRECTION_NAMES: dict[str, str] = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
}


def _materialize_starting_item(
    repo: Repository, run_id: str, player_id: str, gen: EntityGen
) -> str:
    """Create an item entity and place it directly in the player's inventory."""
    name = consistency.unique_entity_name(repo, run_id, gen.name)
    item = repo.create_entity(run_id, EntityType.item, name)
    for stat in gen.stats:
        repo.set_stat(item.id, stat.key, stat.value)
    for fact in gen.facts:
        repo.set_fact(run_id, item.id, fact.key, fact.value)
    if not repo.get_fact(run_id, item.id, "slot"):
        slot = "weapon" if any(s.key == "attack" and s.value > 0 for s in gen.stats) else (
            "armor" if any(s.key == "defense" and s.value > 0 for s in gen.stats) else "misc"
        )
        if slot != "misc":
            repo.set_fact(run_id, item.id, "slot", slot)
    repo.add_to_inventory(player_id, item.id, 1)
    return item.id


def _materialize_entity(
    repo: Repository, run_id: str, location_id: str | None, gen: EntityGen
) -> None:
    name = consistency.unique_entity_name(repo, run_id, gen.name)
    entity = repo.create_entity(run_id, gen.type, name)
    if location_id is not None and gen.type in {
        EntityType.npc,
        EntityType.enemy,
        EntityType.item,
    }:
        repo.place_entity(run_id, entity.id, location_id)
    for stat in gen.stats:
        repo.set_stat(entity.id, stat.key, stat.value)
    for fact in gen.facts:
        repo.set_fact(run_id, entity.id, fact.key, fact.value)
    if gen.type == EntityType.item and not repo.get_fact(run_id, entity.id, "slot"):
        slot = "weapon" if any(s.key == "attack" and s.value > 0 for s in gen.stats) else (
            "armor" if any(s.key == "defense" and s.value > 0 for s in gen.stats) else "misc"
        )
        if slot != "misc":
            repo.set_fact(run_id, entity.id, "slot", slot)


def _materialize_location(
    repo: Repository, run_id: str, gen: LocationGen, x: int, y: int
) -> Location:
    name = consistency.unique_location_name(repo, run_id, gen.name)
    location = repo.create_location(
        run_id,
        name=name,
        x=x,
        y=y,
        region=gen.region or "world",
        description=gen.description,
    )
    for fact in gen.facts:
        repo.set_fact(run_id, location.id, fact.key, fact.value)
    for entity_gen in gen.entities:
        _materialize_entity(repo, run_id, location.id, entity_gen)
    return location


def _existing_world_summary(repo: Repository, run: Run) -> dict:
    """A compact view of the world used to keep generation consistent."""
    locations = repo.all_locations(run.id)
    return {
        "world_prompt": run.world_prompt,
        "genre": run.genre,
        "known_locations": [loc.name for loc in locations][-12:],
    }


def generate_seed(repo: Repository, llm: LLMProvider, run: Run, retries: int) -> Location:
    """Create the opening location + player from the run's world prompt."""
    user = (
        f"Player's desired world: {run.world_prompt}\n\n"
        "Seed the opening of this game."
    )
    seed: SeedGen = llm.generate_json(
        GENERATE_SEED_SYSTEM, user, SeedGen, retries=retries
    )

    repo.set_run_genre(run.id, seed.genre)
    start = _materialize_location(repo, run.id, seed.starting_location, x=0, y=0)

    player_name = consistency.unique_entity_name(repo, run.id, seed.player_name)
    player = repo.create_entity(run.id, EntityType.player, player_name)
    repo.place_entity(run.id, player.id, start.id)
    repo.set_run_player(run.id, player.id)
    for stat in seed.player_stats:
        repo.set_stat(player.id, stat.key, stat.value)
    for fact in seed.player_facts:
        repo.set_fact(run.id, player.id, fact.key, fact.value)
    # Guarantee combat-critical stats exist even if the model omitted them.
    if repo.get_stat(player.id, "hp") is None:
        repo.set_stat(player.id, "hp", 20.0)
    if repo.get_stat(player.id, "attack") is None:
        repo.set_stat(player.id, "attack", 5.0)

    for item_gen in seed.starting_items:
        if item_gen.type != EntityType.item:
            continue
        item_id = _materialize_starting_item(repo, run.id, player.id, item_gen)
        try_auto_equip(repo, run.id, player.id, item_id)

    if seed.opening_quest:
        repo.create_quest(run.id, title="Opening", summary=seed.opening_quest)

    repo.commit()
    return start


def generate_adjacent_location(
    repo: Repository,
    llm: LLMProvider,
    run: Run,
    from_location: Location,
    direction: str,
    retries: int,
) -> tuple[Location, bool]:
    """Return the location reached by moving ``direction`` from ``from_location``.

    The bool is True if a new location was generated, False if an existing one
    was reached (map collision -> link). Either way the bidirectional connection
    is ensured.
    """
    dx, dy = DIRECTION_DELTAS[direction]
    tx, ty = from_location.x + dx, from_location.y + dy

    existing = repo.location_at(run.id, from_location.region, tx, ty)
    if existing is not None:
        repo.add_connection(run.id, from_location.id, existing.id, direction)
        repo.add_connection(run.id, existing.id, from_location.id, OPPOSITE[direction])
        repo.commit()
        return existing, False

    context = _existing_world_summary(repo, run)
    user = (
        f"World context:\n{json.dumps(context, ensure_ascii=False)}\n\n"
        f"The player travels {DIRECTION_NAMES[direction]} from "
        f"'{from_location.name}'. Generate the location they arrive at."
    )
    gen: LocationGen = llm.generate_json(
        GENERATE_LOCATION_SYSTEM, user, LocationGen, retries=retries
    )
    new_location = _materialize_location(repo, run.id, gen, x=tx, y=ty)
    repo.add_connection(run.id, from_location.id, new_location.id, direction)
    repo.add_connection(run.id, new_location.id, from_location.id, OPPOSITE[direction])
    repo.commit()
    return new_location, True
