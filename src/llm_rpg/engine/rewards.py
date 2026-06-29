"""Materialize NPC grants and enemy loot drops into real inventory rows."""

from __future__ import annotations

from ..state.models import DialogueGen, Entity, EntityGen, EntityType, ItemGrantGen
from ..state.repository import Repository
from .equipment import try_auto_equip
from .items import (
    add_item_to_inventory,
    find_item_by_name,
    format_item_qty,
    place_item_at_location,
)

_GIVE_PHRASES = (
    "take this",
    "take these",
    "here is",
    "here are",
    "here's",
    "i give you",
    "i'll give you",
    "ill give you",
    "give you",
    "hand you",
    "as a reward",
    "your reward",
    "payment of",
    "paid you",
    "receive this",
    "accept this",
    "yours to keep",
    "have this",
    "have these",
)

_REWARD_ASK_WORDS = (
    "reward",
    "pay",
    "gold",
    "payment",
    "defeat",
    "killed",
    "beat",
    "can i get",
    "give me",
    "hand over",
)


def npc_reply_indicates_transfer(npc_reply: str) -> bool:
    """True when the spoken line clearly hands something over."""
    text = npc_reply.lower()
    return any(phrase in text for phrase in _GIVE_PHRASES)


def _player_asked_for_reward(player_said: str | None) -> bool:
    if not player_said:
        return False
    text = player_said.lower()
    return any(word in text for word in _REWARD_ASK_WORDS)


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
        item, qty = existing
        repo.add_to_inventory(player_id, item.id, amount)
        return format_item_qty(f"{amount} gold (added to {item.name})", qty + amount)
    gen = ItemGrantGen(
        name="Gold Coins",
        qty=amount,
        facts=[{"key": "kind", "value": "gold"}, {"key": "slot", "value": "misc"}],
    )
    item, total = add_item_to_inventory(repo, run_id, player_id, gen, qty=amount)
    return format_item_qty(f"{amount} gold", total)


def grant_item_to_player(
    repo: Repository,
    run_id: str,
    player_id: str,
    grant: ItemGrantGen,
) -> str:
    """Add or stack an item in the player's inventory."""
    item, total = add_item_to_inventory(
        repo, run_id, player_id, grant, qty=grant.qty
    )
    try_auto_equip(repo, run_id, player_id, item.id)
    return format_item_qty(item.name, total)


def apply_dialogue_grants(
    repo: Repository,
    run_id: str,
    player_id: str,
    reply: DialogueGen,
    *,
    defeated_enemies: list[str],
    player_said: str | None,
) -> list[str]:
    """Turn structured NPC grants into inventory changes when the exchange warrants it."""
    if not reply.grant_items and reply.grant_gold <= 0:
        return []

    if not npc_reply_indicates_transfer(reply.npc_reply):
        return []

    if _player_asked_for_reward(player_said) and not defeated_enemies:
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
    *,
    player_id: str | None = None,
) -> list[str]:
    """Leave loot at the location (or stack into the player's pack) and remove the corpse."""
    repo.place_entity(run_id, enemy.id, None)

    drops: list[str] = []
    drop_names: list[str] = []
    drop_item = repo.get_fact(run_id, enemy.id, "drop_item")
    if drop_item:
        drop_names.append(drop_item.strip())
    drop_list = repo.get_fact(run_id, enemy.id, "drop_items")
    if drop_list:
        drop_names.extend(part.strip() for part in drop_list.split(",") if part.strip())

    for raw_name in drop_names:
        gen = EntityGen(
            type=EntityType.item,
            name=raw_name,
            facts=[{"key": "slot", "value": "misc"}],
        )
        existing = find_item_by_name(repo, run_id, raw_name)
        if (
            existing is not None
            and player_id is not None
            and repo.inventory_holder(existing.id) == player_id
        ):
            repo.add_to_inventory(player_id, existing.id, 1)
            total = repo.inventory_qty(player_id, existing.id)
            drops.append(format_item_qty(f"{existing.name} (to your pack)", total))
            continue

        placed = place_item_at_location(repo, run_id, location_id, gen)
        if placed is not None:
            drops.append(placed.name)

    return drops
