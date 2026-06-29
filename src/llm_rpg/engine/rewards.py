"""Materialize NPC grants and enemy loot drops into real inventory rows."""

from __future__ import annotations

from ..state.models import DialogueGen, Entity, EntityGen, EntityType, ItemGrantGen
from ..state.repository import Repository
from . import consistency
from .equipment import try_auto_equip


def _infer_slot(gen: EntityGen | ItemGrantGen) -> str:
    for fact in gen.facts:
        if fact.key == "slot":
            return fact.value
    if any(s.key == "attack" and s.value > 0 for s in gen.stats):
        return "weapon"
    if any(s.key == "defense" and s.value > 0 for s in gen.stats):
        return "armor"
    return "misc"


def _create_item_entity(
    repo: Repository, run_id: str, gen: EntityGen | ItemGrantGen
) -> Entity:
    name = consistency.unique_entity_name(repo, run_id, gen.name)
    item = repo.create_entity(run_id, EntityType.item, name)
    for stat in gen.stats:
        repo.set_stat(item.id, stat.key, stat.value)
    for fact in gen.facts:
        repo.set_fact(run_id, item.id, fact.key, fact.value)
    if not repo.get_fact(run_id, item.id, "slot"):
        slot = _infer_slot(gen)
        if slot != "misc":
            repo.set_fact(run_id, item.id, "slot", slot)
    return item


def _find_gold_stack(repo: Repository, player_id: str) -> tuple[Entity, int] | None:
    for item, qty in repo.inventory(player_id):
        name_l = item.name.lower()
        if "gold" in name_l or repo.get_fact(item.run_id, item.id, "kind") == "gold":
            return item, qty
    return None


def grant_gold_to_player(
    repo: Repository, run_id: str, player_id: str, amount: int
) -> str | None:
    if amount <= 0:
        return None
    existing = _find_gold_stack(repo, player_id)
    if existing:
        item, _qty = existing
        repo.add_to_inventory(player_id, item.id, amount)
        return f"{amount} gold (added to {item.name})"
    gen = ItemGrantGen(
        name="Gold Coins",
        qty=amount,
        facts=[{"key": "kind", "value": "gold"}, {"key": "slot", "value": "misc"}],
    )
    item = _create_item_entity(repo, run_id, gen)
    repo.add_to_inventory(player_id, item.id, amount)
    return f"{amount} gold"


def grant_item_to_player(
    repo: Repository,
    run_id: str,
    player_id: str,
    grant: ItemGrantGen,
) -> str:
    """Add or stack an item in the player's inventory."""
    target_l = grant.name.strip().lower()
    for item, qty in repo.inventory(player_id):
        if item.name.lower() == target_l or target_l in item.name.lower():
            repo.add_to_inventory(player_id, item.id, grant.qty)
            total = qty + grant.qty
            return f"{grant.name} x{total}" if total > 1 else grant.name

    item = _create_item_entity(repo, run_id, grant)
    repo.add_to_inventory(player_id, item.id, grant.qty)
    try_auto_equip(repo, run_id, player_id, item.id)
    if grant.qty > 1:
        return f"{item.name} x{grant.qty}"
    return item.name


def apply_dialogue_grants(
    repo: Repository,
    run_id: str,
    player_id: str,
    reply: DialogueGen,
    *,
    defeated_enemies: list[str],
    player_said: str | None,
) -> list[str]:
    """Turn structured NPC grants into inventory changes."""
    if not reply.grant_items and reply.grant_gold <= 0:
        return []

    player_l = (player_said or "").lower()
    reward_context = any(
        word in player_l
        for word in ("reward", "pay", "gold", "payment", "defeat", "killed", "beat")
    )
    if reward_context and not defeated_enemies:
        return []

    granted: list[str] = []
    for item_grant in reply.grant_items:
        granted.append(grant_item_to_player(repo, run_id, player_id, item_grant))
    gold_note = grant_gold_to_player(repo, run_id, player_id, reply.grant_gold)
    if gold_note:
        granted.append(gold_note)
    return granted


def spawn_enemy_drops(
    repo: Repository,
    run_id: str,
    location_id: str,
    enemy: Entity,
) -> list[str]:
    """Leave loot at the location and remove the corpse from the room."""
    repo.place_entity(run_id, enemy.id, None)

    drops: list[str] = []
    drop_item = repo.get_fact(run_id, enemy.id, "drop_item")
    if drop_item:
        gen = EntityGen(
            type=EntityType.item,
            name=drop_item,
            facts=[{"key": "slot", "value": "misc"}],
        )
        name = consistency.unique_entity_name(repo, run_id, gen.name)
        item = repo.create_entity(run_id, EntityType.item, name)
        for fact in gen.facts:
            repo.set_fact(run_id, item.id, fact.key, fact.value)
        repo.place_entity(run_id, item.id, location_id)
        drops.append(item.name)

    drop_list = repo.get_fact(run_id, enemy.id, "drop_items")
    if drop_list:
        for raw in drop_list.split(","):
            item_name = raw.strip()
            if not item_name:
                continue
            gen = EntityGen(
                type=EntityType.item,
                name=item_name,
                facts=[{"key": "slot", "value": "misc"}],
            )
            name = consistency.unique_entity_name(repo, run_id, gen.name)
            item = repo.create_entity(run_id, EntityType.item, name)
            for fact in gen.facts:
                repo.set_fact(run_id, item.id, fact.key, fact.value)
            repo.place_entity(run_id, item.id, location_id)
            drops.append(item.name)

    return drops
