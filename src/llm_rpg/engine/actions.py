"""Action handlers.

Each handler applies one validated action deterministically against the world
state and returns a *ground-truth result*: a plain-language ``summary`` (what
actually happened) plus structured ``details``. The narrator later dresses this
up but may not change the facts. The mock provider simply echoes ``summary``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..llm.base import LLMProvider
from ..rng import GameRNG
from ..state.models import Action, ActionType, Entity, EntityType, Run
from ..state.repository import Repository
from . import combat, world_gen
from .consistency import ConsistencyError
from .dialogue import generate_npc_reply, persist_dialogue
from .equipment import (
    get_equipped,
    item_slot,
    player_loadout,
    try_auto_equip,
)
from .rewards import spawn_enemy_drops


@dataclass
class TurnContext:
    repo: Repository
    llm: LLMProvider
    run: Run
    rng: GameRNG
    retries: int = 2
    turn: int = 0
    world_context: dict = field(default_factory=dict)


@dataclass
class ActionResult:
    action_type: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


def _player_location(ctx: TurnContext) -> str | None:
    if not ctx.run.player_id:
        return None
    return ctx.repo.entity_location(ctx.run.player_id)


def _find_present_entity(
    ctx: TurnContext, location_id: str, target: str
) -> Entity | None:
    """Resolve a possibly-fuzzy target name to a present entity."""
    if not target:
        return None
    target_l = target.strip().lower()
    present = ctx.repo.entities_at(location_id, exclude_id=ctx.run.player_id)
    for entity in present:  # exact match first
        if entity.name.lower() == target_l:
            return entity
    for entity in present:  # then substring either direction
        name_l = entity.name.lower()
        if target_l in name_l or name_l in target_l:
            return entity
    return None


def handle_look(ctx: TurnContext, action: Action) -> ActionResult:
    from .memory import location_context

    location_id = _player_location(ctx)
    if not location_id:
        return ActionResult("look", "There is nothing here yet.")
    lc = location_context(ctx.repo, ctx.run, location_id)
    exits = ", ".join(e["direction"] for e in lc.get("exits", [])) or "none yet"
    present = lc.get("present_entities", [])
    who = ", ".join(e["name"] for e in present) if present else "no one else"
    summary = (
        f"{lc['name']}. {lc['description']} "
        f"Exits: {exits}. Present: {who}."
    )
    return ActionResult("look", summary, {"location": lc})


def handle_move(ctx: TurnContext, action: Action) -> ActionResult:
    location_id = _player_location(ctx)
    location = ctx.repo.get_location(location_id) if location_id else None
    if location is None:
        return ActionResult("move", "You have nowhere to move from yet.")
    direction = (action.direction or "").lower()
    if direction not in world_gen.DIRECTION_DELTAS:
        return ActionResult(
            "move", "You can't tell which direction that is.", {"failed": True}
        )

    existing = ctx.repo.connection_in_direction(location.id, direction)
    if existing is not None:
        destination = ctx.repo.get_location(existing.to_location)
        new = False
    else:
        destination, new = world_gen.generate_adjacent_location(
            ctx.repo, ctx.llm, ctx.run, location, direction, ctx.retries
        )

    ctx.repo.place_entity(ctx.run.id, ctx.run.player_id, destination.id)
    ctx.repo.commit()
    dir_name = world_gen.DIRECTION_NAMES[direction]
    verb = "arrive at" if new else "return to"
    summary = (
        f"You travel {dir_name} and {verb} {destination.name}. "
        f"{destination.description}"
    )
    return ActionResult(
        "move",
        summary,
        {"destination": destination.name, "newly_generated": new},
    )


def handle_take(ctx: TurnContext, action: Action) -> ActionResult:
    location_id = _player_location(ctx)
    if not location_id:
        return ActionResult("take", "There is nothing to take.")
    entity = _find_present_entity(ctx, location_id, action.target or "")
    if entity is None or entity.type != EntityType.item:
        target = action.target or "that"
        return ActionResult(
            "take", f"There is no {target} here to take.", {"failed": True}
        )
    ctx.repo.place_entity(ctx.run.id, entity.id, None)
    ctx.repo.add_to_inventory(ctx.run.player_id, entity.id, 1)
    slot = try_auto_equip(ctx.repo, ctx.run.id, ctx.run.player_id, entity.id)
    ctx.repo.commit()
    msg = f"You take the {entity.name}."
    if slot:
        msg += f" You equip it as your {slot}."
    return ActionResult("take", msg, {"item": entity.name, "equipped_slot": slot})


def handle_talk(ctx: TurnContext, action: Action) -> ActionResult:
    location_id = _player_location(ctx)
    if not location_id:
        return ActionResult("talk", "There is no one to talk to.")
    entity = _find_present_entity(ctx, location_id, action.target or "")
    if entity is None or entity.type not in {EntityType.npc, EntityType.enemy}:
        target = action.target or "anyone"
        return ActionResult(
            "talk", f"There is no {target} here to talk to.", {"failed": True}
        )
    player_said = (action.text or "").strip() or None
    reply = generate_npc_reply(
        ctx.repo,
        ctx.llm,
        ctx.run,
        entity,
        player_said,
        turn=ctx.turn,
        world_context=ctx.world_context,
        retries=ctx.retries,
    )
    granted = persist_dialogue(
        ctx.repo,
        ctx.run.id,
        entity.id,
        ctx.turn,
        player_said,
        reply,
        player_id=ctx.run.player_id,
        defeated_enemies=ctx.world_context.get("interaction", {}).get(
            "defeated_enemies", []
        ),
    )
    ctx.repo.commit()

    if player_said:
        summary = (
            f"You say to {entity.name}: '{player_said}'. "
            f"{entity.name} replies: '{reply.npc_reply}'"
        )
    else:
        summary = f"{entity.name} replies: '{reply.npc_reply}'"

    if granted:
        summary += f" You receive: {', '.join(granted)}."
    return ActionResult(
        "talk",
        summary,
        {
            "npc": entity.name,
            "player_said": player_said or "",
            "npc_reply": reply.npc_reply,
            "new_facts": {f.key: f.value for f in reply.new_facts},
            "granted": granted,
        },
    )


def handle_attack(ctx: TurnContext, action: Action) -> ActionResult:
    location_id = _player_location(ctx)
    if not location_id:
        return ActionResult("attack", "There is nothing to attack.")
    entity = _find_present_entity(ctx, location_id, action.target or "")
    if entity is None or entity.type not in {EntityType.enemy, EntityType.npc}:
        target = action.target or "that"
        return ActionResult(
            "attack", f"There is no {target} here to attack.", {"failed": True}
        )
    if entity.status == "dead":
        return ActionResult(
            "attack", f"{entity.name} is already dead.", {"failed": True}
        )
    try:
        result = combat.resolve_attack(
            ctx.repo, ctx.rng, ctx.run.player_id, entity.id, run_id=ctx.run.id
        )
    except ConsistencyError as exc:
        return ActionResult("attack", str(exc), {"failed": True})
    drops: list[str] = []
    if result.defender_dead and location_id:
        drops = spawn_enemy_drops(ctx.repo, ctx.run.id, location_id, entity)
    ctx.repo.commit()

    weapon = get_equipped(ctx.repo, ctx.run.id, ctx.run.player_id, "weapon")
    weapon_note = ""
    if weapon:
        weapon_note = f" (using {weapon.name})"
    parts = [
        f"You strike {result.defender_name} for {result.damage_to_defender} damage"
        f"{weapon_note}."
    ]
    if result.defender_dead:
        parts.append(f"{result.defender_name} falls, defeated.")
        if drops:
            parts.append(f"Left behind: {', '.join(drops)}.")
    else:
        parts.append(
            f"{result.defender_name} has {int(result.defender_hp)} HP left "
            f"and hits back for {result.damage_to_attacker}."
        )
    if result.attacker_dead:
        parts.append("The blow is fatal -- you collapse.")
    else:
        parts.append(f"You have {int(result.attacker_hp)} HP remaining.")
    summary = " ".join(parts)
    return ActionResult(
        "attack",
        summary,
        {
            "defender": result.defender_name,
            "damage_dealt": result.damage_to_defender,
            "damage_taken": result.damage_to_attacker,
            "defender_hp": result.defender_hp,
            "player_hp": result.attacker_hp,
            "defender_dead": result.defender_dead,
            "player_dead": result.attacker_dead,
            "drops": drops,
            "attack_used": result.attacker_attack_used,
            "defense_used": result.attacker_defense_used,
        },
    )


def _find_inventory_item(ctx: TurnContext, target: str) -> Entity | None:
    target_l = target.strip().lower()
    if not target_l:
        return None
    for item, _qty in ctx.repo.inventory(ctx.run.player_id):
        name_l = item.name.lower()
        if name_l == target_l or target_l in name_l or name_l in target_l:
            return item
    return None


def handle_equip(ctx: TurnContext, action: Action) -> ActionResult:
    if not ctx.run.player_id:
        return ActionResult("equip", "You have nothing to equip.")
    item = _find_inventory_item(ctx, action.target or "")
    if item is None:
        return ActionResult(
            "equip",
            f"You don't carry {action.target or 'that'}.",
            {"failed": True},
        )
    slot = item_slot(ctx.repo, ctx.run.id, item.id)
    if slot not in {"weapon", "armor"}:
        return ActionResult(
            "equip",
            f"The {item.name} is not something you can wield or wear.",
            {"failed": True},
        )
    ctx.repo.equip(ctx.run.player_id, slot, item.id)
    ctx.repo.commit()
    loadout = player_loadout(ctx.repo, ctx.run, ctx.run.player_id)
    eff = loadout["effective_stats"]
    return ActionResult(
        "equip",
        f"You equip the {item.name} as your {slot}. "
        f"Effective attack: {int(eff['attack'])}, defense: {int(eff['defense'])}.",
        {"item": item.name, "slot": slot, "effective_stats": eff},
    )


def handle_inventory(ctx: TurnContext, action: Action) -> ActionResult:
    if not ctx.run.player_id:
        return ActionResult("inventory", "You are carrying nothing.")
    items = ctx.repo.inventory(ctx.run.player_id)
    loadout = player_loadout(ctx.repo, ctx.run, ctx.run.player_id)
    eff = loadout["effective_stats"]
    stats_note = (
        f" Effective attack: {int(eff['attack'])}, "
        f"defense: {int(eff['defense'])}, "
        f"HP: {int(eff['hp'] or 0)}."
    )
    equipped_lines = []
    for slot, data in loadout["equipped"].items():
        if data:
            bonus = data.get("stats", {})
            extra = ""
            if bonus.get("attack"):
                extra = f" (+{int(bonus['attack'])} atk)"
            elif bonus.get("defense"):
                extra = f" (+{int(bonus['defense'])} def)"
            equipped_lines.append(f"{slot}: {data['name']}{extra}")
    equip_note = ""
    if equipped_lines:
        equip_note = " Equipped: " + ", ".join(equipped_lines) + "."
    if not items:
        return ActionResult(
            "inventory",
            f"You are carrying nothing.{equip_note}{stats_note}",
            {"items": [], "loadout": loadout},
        )
    listing = ", ".join(
        f"{item.name}" + (f" x{qty}" if qty > 1 else "") for item, qty in items
    )
    return ActionResult(
        "inventory",
        f"You are carrying: {listing}.{equip_note}{stats_note}",
        {
            "items": [{"name": item.name, "qty": qty} for item, qty in items],
            "loadout": loadout,
        },
    )


def handle_use(ctx: TurnContext, action: Action) -> ActionResult:
    if not ctx.run.player_id:
        return ActionResult("use", "You have nothing to use.")
    item = _find_inventory_item(ctx, action.target or "")
    if item is None:
        return ActionResult(
            "use", f"You don't have {action.target or 'that'}.", {"failed": True}
        )
    slot = item_slot(ctx.repo, ctx.run.id, item.id)
    if slot in {"weapon", "armor"}:
        return handle_equip(ctx, Action(type=ActionType.equip, target=item.name))
    return ActionResult("use", f"You use the {item.name}.", {"item": item.name})


def handle_say(ctx: TurnContext, action: Action) -> ActionResult:
    text = action.text or action.target or ""
    if not text:
        return ActionResult("say", "You open your mouth, but say nothing.")
    return ActionResult("say", f"You say aloud: '{text}'.", {"said": text})


def handle_unknown(ctx: TurnContext, action: Action) -> ActionResult:
    return ActionResult("unknown", "You aren't sure how to do that.")


HANDLERS = {
    "look": handle_look,
    "move": handle_move,
    "take": handle_take,
    "talk": handle_talk,
    "attack": handle_attack,
    "inventory": handle_inventory,
    "equip": handle_equip,
    "use": handle_use,
    "say": handle_say,
    "unknown": handle_unknown,
}
