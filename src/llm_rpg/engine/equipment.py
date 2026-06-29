"""Equipment slots, effective combat stats, and loadout for story context."""

from __future__ import annotations

from ..state.models import Entity, Run
from ..state.repository import Repository

SLOTS = ("weapon", "armor")
DEFAULT_SLOT = "misc"


def item_slot(repo: Repository, run_id: str, item_id: str) -> str:
    """Return the equipment slot for an item (weapon, armor, or misc)."""
    slot = repo.get_fact(run_id, item_id, "slot")
    if slot in SLOTS:
        return slot
    stats = repo.get_stats(item_id)
    if stats.get("attack", 0) > 0:
        return "weapon"
    if stats.get("defense", 0) > 0:
        return "armor"
    return DEFAULT_SLOT


def _item_brief(repo: Repository, run_id: str, item: Entity) -> dict:
    return {
        "name": item.name,
        "slot": item_slot(repo, run_id, item.id),
        "stats": repo.get_stats(item.id),
        "facts": {f.key: f.value for f in repo.facts_for(run_id, item.id)},
    }


def get_equipped(repo: Repository, run_id: str, owner_id: str, slot: str) -> Entity | None:
    item_id = repo.get_equipped(owner_id, slot)
    if not item_id:
        return None
    return repo.get_entity(item_id)


def effective_attack(repo: Repository, run_id: str, entity_id: str) -> float:
    base = repo.get_stat(entity_id, "attack") or 1.0
    weapon = get_equipped(repo, run_id, entity_id, "weapon")
    if weapon is None:
        return base
    bonus = repo.get_stat(weapon.id, "attack") or 0.0
    return base + bonus


def effective_defense(repo: Repository, run_id: str, entity_id: str) -> float:
    armor = get_equipped(repo, run_id, entity_id, "armor")
    if armor is None:
        return 0.0
    return repo.get_stat(armor.id, "defense") or 0.0


def player_loadout(repo: Repository, run: Run, player_id: str) -> dict:
    """Equipped gear + effective stats for combat and story context."""
    equipped: dict[str, dict | None] = {}
    for slot in SLOTS:
        item = get_equipped(repo, run.id, player_id, slot)
        equipped[slot] = _item_brief(repo, run.id, item) if item else None
    return {
        "equipped": equipped,
        "effective_stats": {
            "attack": effective_attack(repo, run.id, player_id),
            "defense": effective_defense(repo, run.id, player_id),
            "hp": repo.get_stat(player_id, "hp"),
        },
    }


def try_auto_equip(repo: Repository, run_id: str, owner_id: str, item_id: str) -> str | None:
    """Equip an item if its slot is empty. Returns slot name if equipped."""
    slot = item_slot(repo, run_id, item_id)
    if slot not in SLOTS:
        return None
    if repo.get_equipped(owner_id, slot):
        return None
    repo.equip(owner_id, slot, item_id)
    return slot
