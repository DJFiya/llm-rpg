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
from collections.abc import Callable

from ..llm.base import LLMProvider
from ..llm.prompts import (
    GENERATE_LOCATION_SYSTEM,
    GENERATE_SEED_SYSTEM,
)
from ..state.models import (
    CatalogItemGen,
    EntityGen,
    EntityType,
    Location,
    LocationGen,
    MappedLocationGen,
    Run,
    SeedConnectionGen,
    SeedGen,
)
from ..state.repository import Repository
from . import consistency
from .catalog import catalog_context, materialize_catalog, merge_catalog
from .equipment import try_auto_equip
from .matching import normalize_item_base_name

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


def _slot_from_gen(gen: EntityGen) -> str:
    for fact in gen.facts:
        if fact.key == "slot":
            return fact.value
    if any(s.key == "attack" and s.value > 0 for s in gen.stats):
        return "weapon"
    if any(s.key == "defense" and s.value > 0 for s in gen.stats):
        return "armor"
    if any(s.key == "heal_hp" and s.value > 0 for s in gen.stats):
        return "consumable"
    return "misc"


def _starting_items_as_catalog(starting_items: list[EntityGen]) -> list[CatalogItemGen]:
    entries: list[CatalogItemGen] = []
    for item in starting_items:
        if item.type != EntityType.item:
            continue
        entries.append(
            CatalogItemGen(
                name=normalize_item_base_name(item.name),
                slot=_slot_from_gen(item),
                stats=list(item.stats),
                facts=list(item.facts),
            )
        )
    return entries


def _materialize_starting_item(
    repo: Repository, run_id: str, player_id: str, gen: EntityGen
) -> str:
    """Create or reuse an item entity and place it in the player's inventory."""
    from .items import add_item_to_inventory

    item, _total = add_item_to_inventory(repo, run_id, player_id, gen, qty=1)
    return item.id


def _materialize_entity(
    repo: Repository, run_id: str, location_id: str | None, gen: EntityGen
) -> None:
    if gen.type == EntityType.item:
        from .items import place_item_at_location, resolve_or_create_item

        item, _created = resolve_or_create_item(repo, run_id, gen)
        if location_id is not None:
            place_item_at_location(repo, run_id, location_id, gen)
        return

    name = consistency.unique_entity_name(repo, run_id, gen.name)
    entity = repo.create_entity(run_id, gen.type, name)
    if location_id is not None and gen.type in {EntityType.npc, EntityType.enemy}:
        repo.place_entity(run_id, entity.id, location_id)
    for stat in gen.stats:
        repo.set_stat(entity.id, stat.key, stat.value)
    for fact in gen.facts:
        repo.set_fact(run_id, entity.id, fact.key, fact.value)


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
        "item_catalog": catalog_context(repo, run.id),
    }


def _connection_coords_match(
    from_loc: Location, to_loc: Location, direction: str
) -> bool:
    dx, dy = DIRECTION_DELTAS.get(direction, (0, 0))
    return from_loc.x + dx == to_loc.x and from_loc.y + dy == to_loc.y


def _materialize_initial_map(
    repo: Repository,
    run_id: str,
    start: Location,
    start_key: str,
    additional: list[MappedLocationGen],
    connections: list[SeedConnectionGen],
) -> None:
    """Place pre-generated locations and wire bidirectional exits."""
    by_key: dict[str, Location] = {start_key: start}

    for mapped in additional:
        region = mapped.location.region or "world"
        if repo.location_at(run_id, region, mapped.x, mapped.y):
            continue
        loc = _materialize_location(
            repo, run_id, mapped.location, x=mapped.x, y=mapped.y
        )
        by_key[mapped.location.name] = loc

    for conn in connections:
        direction = conn.direction.lower()
        if direction not in DIRECTION_DELTAS:
            continue
        src = by_key.get(conn.from_location)
        dst = by_key.get(conn.to_location)
        if src is None or dst is None:
            continue
        if not _connection_coords_match(src, dst, direction):
            continue
        repo.add_connection(run_id, src.id, dst.id, direction)
        repo.add_connection(
            run_id, dst.id, src.id, OPPOSITE[direction]
        )


ProgressCallback = Callable[[int, str], None] | None


def generate_seed(
    repo: Repository,
    llm: LLMProvider,
    run: Run,
    retries: int,
    *,
    on_progress: ProgressCallback = None,
) -> Location:
    """Create the opening location + player from the run's world prompt."""

    def _progress(pct: int, message: str) -> None:
        if on_progress is not None:
            on_progress(pct, message)

    _progress(5, "Consulting the oracle...")
    user = (
        f"Player's desired world: {run.world_prompt}\n\n"
        "Seed the opening of this game."
    )
    seed: SeedGen = llm.generate_json(
        GENERATE_SEED_SYSTEM, user, SeedGen, retries=retries
    )

    _progress(35, "Forging item lore...")
    repo.set_run_genre(run.id, seed.genre)
    catalog = merge_catalog(
        seed.item_catalog + _starting_items_as_catalog(seed.starting_items)
    )
    materialize_catalog(repo, run.id, catalog)

    _progress(50, "Carving the realm...")
    start = _materialize_location(repo, run.id, seed.starting_location, x=0, y=0)
    _materialize_initial_map(
        repo,
        run.id,
        start,
        seed.starting_location.name,
        seed.additional_locations,
        seed.initial_connections,
    )

    _progress(70, "Populating the wilds...")
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
    if repo.get_stat(player.id, "max_hp") is None:
        repo.set_stat(player.id, "max_hp", repo.get_stat(player.id, "hp") or 20.0)
    if repo.get_stat(player.id, "attack") is None:
        repo.set_stat(player.id, "attack", 5.0)

    _progress(85, "Arming the hero...")
    for item_gen in seed.starting_items:
        if item_gen.type != EntityType.item:
            continue
        item_id = _materialize_starting_item(repo, run.id, player.id, item_gen)
        try_auto_equip(repo, run.id, player.id, item_id)

    if seed.opening_quest:
        repo.create_quest(run.id, title="Opening", summary=seed.opening_quest)

    repo.commit()
    _progress(100, "Adventure awaits!")
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
