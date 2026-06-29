"""Shared item resolution: one entity row per item name, quantity via inventory."""

from __future__ import annotations

from ..state.models import Entity, EntityGen, EntityType, ItemGrantGen, StatGen, FactGen
from ..state.repository import Repository
from .matching import normalize_item_base_name


def _gen_facts(gen: EntityGen | ItemGrantGen) -> list[FactGen]:
    return gen.facts


def _gen_stats(gen: EntityGen | ItemGrantGen) -> list[StatGen]:
    return gen.stats


def _infer_slot(gen: EntityGen | ItemGrantGen) -> str:
    for fact in _gen_facts(gen):
        if fact.key == "slot":
            return fact.value
    if any(s.key == "attack" and s.value > 0 for s in _gen_stats(gen)):
        return "weapon"
    if any(s.key == "defense" and s.value > 0 for s in _gen_stats(gen)):
        return "armor"
    return "misc"


def find_item_by_name(repo: Repository, run_id: str, name: str) -> Entity | None:
    """Find an item entity by canonical name (handles legacy '(2)' suffix rows)."""
    base = normalize_item_base_name(name)
    row = repo.conn.execute(
        """SELECT * FROM entities
           WHERE run_id = ? AND type = ?
             AND (name = ? COLLATE NOCASE OR name LIKE ? ESCAPE '\\')
           ORDER BY CASE WHEN name = ? COLLATE NOCASE THEN 0 ELSE 1 END, name
           LIMIT 1""",
        (run_id, EntityType.item.value, base, f"{base} (%", base),
    ).fetchone()
    return Entity.model_validate(dict(row)) if row else None


def _apply_item_template(
    repo: Repository, run_id: str, item_id: str, gen: EntityGen | ItemGrantGen
) -> None:
    for stat in _gen_stats(gen):
        if repo.get_stat(item_id, stat.key) is None:
            repo.set_stat(item_id, stat.key, stat.value)
    for fact in _gen_facts(gen):
        if repo.get_fact(run_id, item_id, fact.key) is None:
            repo.set_fact(run_id, item_id, fact.key, fact.value)
    if not repo.get_fact(run_id, item_id, "slot"):
        slot = _infer_slot(gen)
        if slot != "misc":
            repo.set_fact(run_id, item_id, "slot", slot)


def resolve_or_create_item(
    repo: Repository, run_id: str, gen: EntityGen | ItemGrantGen
) -> tuple[Entity, bool]:
    """Return an item entity, creating it only when the name is new."""
    existing = find_item_by_name(repo, run_id, gen.name)
    if existing is not None:
        _apply_item_template(repo, run_id, existing.id, gen)
        return existing, False

    canonical = normalize_item_base_name(gen.name)
    item = repo.create_entity(run_id, EntityType.item, canonical)
    _apply_item_template(repo, run_id, item.id, gen)
    return item, True


def add_item_to_inventory(
    repo: Repository,
    run_id: str,
    player_id: str,
    gen: EntityGen | ItemGrantGen,
    qty: int = 1,
) -> tuple[Entity, int]:
    """Stack onto an existing item row or create one, returning (item, new_total_qty)."""
    item, _created = resolve_or_create_item(repo, run_id, gen)
    holder = repo.inventory_holder(item.id)
    if holder and holder != player_id:
        raise ValueError(f"{item.name} is already carried by someone else")

    if holder == player_id:
        current = repo.inventory_qty(player_id, item.id)
        repo.add_to_inventory(player_id, item.id, qty)
        return item, current + qty

    if repo.entity_location(item.id) is not None:
        repo.place_entity(run_id, item.id, None)
    repo.add_to_inventory(player_id, item.id, qty)
    return item, qty


def place_item_at_location(
    repo: Repository,
    run_id: str,
    location_id: str,
    gen: EntityGen | ItemGrantGen,
) -> Entity | None:
    """Place an item in a room, reusing the existing entity when possible."""
    item, _created = resolve_or_create_item(repo, run_id, gen)
    holder = repo.inventory_holder(item.id)
    if holder is not None:
        return None

    current_loc = repo.entity_location(item.id)
    if current_loc == location_id:
        return item
    if current_loc is not None:
        return None

    repo.place_entity(run_id, item.id, location_id)
    return item


def format_item_qty(name: str, qty: int) -> str:
    return f"{name} x{qty}" if qty > 1 else name
