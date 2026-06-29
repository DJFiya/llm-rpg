"""Consumable item effects (healing, etc.) with numeric stats from the catalog."""

from __future__ import annotations

from dataclasses import dataclass

from ..state.repository import Repository


@dataclass
class ConsumableResult:
    item_name: str
    heal_hp: float = 0.0
    hp_before: float = 0.0
    hp_after: float = 0.0
    consumed: bool = True
    qty_remaining: int = 0


def is_consumable(repo: Repository, run_id: str, item_id: str) -> bool:
    if repo.get_fact(run_id, item_id, "consumable") == "true":
        return True
    slot = repo.get_fact(run_id, item_id, "slot") or ""
    if slot == "consumable":
        return True
    heal = repo.get_stat(item_id, "heal_hp")
    return heal is not None and heal > 0


def item_effect_summary(repo: Repository, item_id: str) -> str:
    parts: list[str] = []
    heal = repo.get_stat(item_id, "heal_hp")
    if heal and heal > 0:
        parts.append(f"heals {int(heal)} HP")
    attack = repo.get_stat(item_id, "attack")
    if attack and attack > 0:
        parts.append(f"+{int(attack)} attack")
    defense = repo.get_stat(item_id, "defense")
    if defense and defense > 0:
        parts.append(f"+{int(defense)} defense")
    return ", ".join(parts) if parts else "no listed effect"


def use_consumable(
    repo: Repository,
    run_id: str,
    player_id: str,
    item_id: str,
    *,
    qty: int = 1,
) -> ConsumableResult | None:
    """Apply consumable stats and decrement stack. Returns None if not consumable."""
    if not is_consumable(repo, run_id, item_id):
        return None

    item = repo.get_entity(item_id)
    assert item is not None

    hp_before = repo.get_stat(player_id, "hp") or 0.0
    max_hp = repo.get_stat(player_id, "max_hp") or hp_before or 20.0
    heal = repo.get_stat(item_id, "heal_hp") or 0.0
    hp_after = min(max_hp, hp_before + heal) if heal > 0 else hp_before

    if heal > 0:
        repo.set_stat(player_id, "hp", hp_after)
    if repo.get_stat(player_id, "max_hp") is None:
        repo.set_stat(player_id, "max_hp", max(max_hp, hp_after))

    new_qty = qty - 1
    if new_qty <= 0:
        repo.remove_from_inventory(player_id, item_id)
    else:
        repo.set_inventory_qty(player_id, item_id, new_qty)

    return ConsumableResult(
        item_name=item.name,
        heal_hp=heal,
        hp_before=hp_before,
        hp_after=hp_after,
        consumed=new_qty <= 0,
        qty_remaining=max(0, new_qty),
    )
