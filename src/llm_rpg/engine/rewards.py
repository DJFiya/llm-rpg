"""Materialize NPC grants and enemy loot drops into real inventory rows."""

from __future__ import annotations

import re

from ..state.models import DialogueGen, Entity, EntityGen, EntityType, ItemGrantGen
from ..state.repository import Repository
from .catalog import grant_spec_for_name
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

_KILL_REWARD_PHRASES = (
    "reward for",
    "reward for defeating",
    "reward for killing",
    "payment for",
    "paid for killing",
    "since i defeated",
    "since i killed",
    "since i beat",
    "for defeating",
    "for killing",
    "for beating",
    "i finish",
    "i finished",
    "i killed",
    "i defeated",
)

_INFER_GRANT_PATTERNS = (
    re.compile(
        r"here(?:'s| is| are)\s+(?:a |an |the |some )?(.+?)(?:\s*[-—]|\s*[,;]|\s+may\b|\s+use\b|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:take|have|accept)\s+(?:this |these )?(?:a |an |the )?(.+?)(?:\s*[-—]|\s*[,;]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"i(?:'ll| will)? give you (?:a |an |the )?(.+?)(?:\s*[-—]|\s*[,;]|$)",
        re.IGNORECASE,
    ),
)

_GOLD_IN_TEXT = re.compile(r"(\d+)\s*gold(?:\s*coins?)?", re.IGNORECASE)

_REJECT_ITEM_FRAGMENTS = (
    "bounty",
    "kill it",
    "collect your",
    "your reward",
    "gold coin",
    "gold coins",
    "well done",
    "as promised",
)


def npc_reply_indicates_transfer(npc_reply: str) -> bool:
    """True when the spoken line clearly hands something over."""
    text = npc_reply.lower()
    return any(phrase in text for phrase in _GIVE_PHRASES)


def _player_asked_for_kill_reward(player_said: str | None) -> bool:
    """True when the player is claiming payment for defeating a foe."""
    if not player_said:
        return False
    text = player_said.lower()
    if any(phrase in text for phrase in _KILL_REWARD_PHRASES):
        return True
    return bool(
        re.search(r"\b(reward|payment)\b", text)
        and re.search(r"\b(defeat|defeated|kill|killed|beat|beaten|finish|finished)\b", text)
    )


def _reply_claims_foe_defeated(npc_reply: str) -> bool:
    text = npc_reply.lower()
    return bool(
        re.search(
            r"\b(finished|defeated|killed|beat|well done|as promised)\b",
            text,
        )
        and re.search(r"\b(reward|gold|payment|promised)\b", text)
    )


def _is_valid_grant_item_name(name: str) -> bool:
    cleaned = name.strip()
    if len(cleaned) < 2 or len(cleaned) > 35:
        return False
    lower = cleaned.lower()
    if _GOLD_IN_TEXT.search(lower):
        return False
    if any(fragment in lower for fragment in _REJECT_ITEM_FRAGMENTS):
        return False
    if lower.startswith("your ") or lower.startswith("here "):
        return False
    return True


def infer_gold_from_reply(npc_reply: str) -> int:
    matches = [int(m) for m in _GOLD_IN_TEXT.findall(npc_reply)]
    return matches[-1] if matches else 0


def _clean_inferred_item_name(raw: str) -> str:
    name = raw.strip(" .,!?:;\"'")
    name = re.sub(r"^(?:a |an |the |some )", "", name, flags=re.IGNORECASE)
    return name.strip(" .,!?:;\"'")


def infer_grants_from_reply(
    repo: Repository, run_id: str, npc_reply: str
) -> list[ItemGrantGen]:
    """Fallback: extract item names when the LLM wrote prose but omitted grant_items."""
    if not npc_reply_indicates_transfer(npc_reply):
        return []
    found: list[ItemGrantGen] = []
    seen: set[str] = set()
    for pattern in _INFER_GRANT_PATTERNS:
        for match in pattern.finditer(npc_reply):
            name = _clean_inferred_item_name(match.group(1))
            if not name or not _is_valid_grant_item_name(name):
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(grant_spec_for_name(repo, run_id, name, qty=1))
    return found


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
        return format_item_qty(item.name, qty + amount)
    gen = ItemGrantGen(
        name="Gold Coins",
        qty=amount,
        facts=[{"key": "kind", "value": "gold"}, {"key": "slot", "value": "misc"}],
    )
    item, total = add_item_to_inventory(repo, run_id, player_id, gen, qty=amount)
    return format_item_qty(item.name, total)


def grant_item_to_player(
    repo: Repository,
    run_id: str,
    player_id: str,
    grant: ItemGrantGen,
) -> str:
    """Add or stack an item in the player's inventory."""
    if not _is_valid_grant_item_name(grant.name):
        return ""
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
    speaker_id: str | None = None,
) -> list[str]:
    """Turn structured NPC grants into inventory changes when the exchange warrants it."""
    if not npc_reply_indicates_transfer(reply.npc_reply):
        return []

    if speaker_id:
        speaker = repo.get_entity(speaker_id)
        if speaker is not None and speaker.type == EntityType.enemy:
            if repo.get_fact(run_id, speaker_id, "can_gift") != "true":
                return []

    kill_reward_context = (
        _player_asked_for_kill_reward(player_said)
        or _reply_claims_foe_defeated(reply.npc_reply)
    )
    if kill_reward_context and not defeated_enemies:
        return []

    grants = list(reply.grant_items)
    if grants:
        grants = [
            grant_spec_for_name(repo, run_id, grant.name, qty=grant.qty)
            for grant in grants
            if _is_valid_grant_item_name(grant.name)
        ]
    if not grants:
        grants = infer_grants_from_reply(repo, run_id, reply.npc_reply)

    gold_amount = reply.grant_gold or infer_gold_from_reply(reply.npc_reply)
    if not grants and gold_amount <= 0:
        return []

    granted: list[str] = []
    for item_grant in grants:
        note = grant_item_to_player(repo, run_id, player_id, item_grant)
        if note:
            granted.append(note)
    gold_note = grant_gold_to_player(repo, run_id, player_id, gold_amount)
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
        if not _is_valid_grant_item_name(raw_name):
            continue
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
