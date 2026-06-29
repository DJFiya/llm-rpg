"""Context retrieval: builds the grounded fact bundle handed to the LLM.

This is what makes the game "remember": instead of relying on the model's
context window, every turn we query the database for exactly the facts relevant
right now (current location, who's present, the player's state, recent events,
active quests, and conversation history with NPCs).
"""

from __future__ import annotations

from ..state.models import EntityType, Run
from ..state.repository import Repository
from .catalog import catalog_context
from .equipment import item_slot, player_loadout
from .world_gen import DIRECTION_NAMES


def _entity_brief(repo: Repository, entity_id: str) -> dict:
    entity = repo.get_entity(entity_id)
    if entity is None:
        return {}
    return {
        "name": entity.name,
        "type": entity.type.value,
        "status": entity.status,
        "stats": repo.get_stats(entity_id),
        "facts": {f.key: f.value for f in repo.facts_for(entity.run_id, entity_id)},
    }


def location_context(repo: Repository, run: Run, location_id: str) -> dict:
    location = repo.get_location(location_id)
    if location is None:
        return {}
    player_id = run.player_id
    present = []
    for e in repo.entities_at(location_id, exclude_id=player_id):
        if e.status == "dead":
            continue
        entry = {
            "name": e.name,
            "type": e.type.value,
            "status": e.status,
            "stats": repo.get_stats(e.id),
        }
        if e.type in {EntityType.npc, EntityType.enemy}:
            entry["facts"] = {
                f.key: f.value for f in repo.facts_for(run.id, e.id)
            }
            history = repo.conversation_with(run.id, e.id, limit=8)
            if history:
                entry["conversation"] = [
                    {"speaker": h.speaker, "text": h.text} for h in history
                ]
        present.append(entry)
    exits = [
        {
            "direction": DIRECTION_NAMES.get(c.direction, c.direction),
            "to": (repo.get_location(c.to_location).name
                   if repo.get_location(c.to_location) else "?"),
        }
        for c in repo.connections_from(location_id)
    ]
    return {
        "name": location.name,
        "region": location.region,
        "coordinates": {"x": location.x, "y": location.y},
        "description": location.description,
        "facts": {f.key: f.value for f in repo.facts_for(run.id, location_id)},
        "present_entities": present,
        "exits": exits,
    }


def build_context(repo: Repository, run: Run, memory_window: int) -> dict:
    """Assemble the full grounded context for the current turn."""
    player_id = run.player_id
    location_id = repo.entity_location(player_id) if player_id else None

    context: dict = {
        "world_prompt": run.world_prompt,
        "genre": run.genre,
        "turn": run.turn,
    }
    if player_id:
        player = _entity_brief(repo, player_id)
        inv = []
        for item, qty in repo.inventory(player_id):
            entry = {"name": item.name, "qty": qty}
            entry["slot"] = item_slot(repo, run.id, item.id)
            entry["stats"] = repo.get_stats(item.id)
            inv.append(entry)
        player["inventory"] = inv
        player["loadout"] = player_loadout(repo, run, player_id)
        context["player"] = player
    if location_id:
        context["location"] = location_context(repo, run, location_id)
    context["active_quests"] = [
        {"title": q.title, "summary": q.summary}
        for q in repo.active_quests(run.id)
    ]
    context["recent_events"] = [
        {"turn": e.turn, "action": e.action_type, "outcome": e.outcome}
        for e in repo.recent_actions(run.id, memory_window)
    ]
    recent = repo.recent_actions(run.id, 1)
    last = recent[-1] if recent else None
    context["interaction"] = {
        "focus_npc": repo.recent_conversation_partner_name(run.id),
        "last_action": last.action_type if last else None,
        "last_outcome": last.outcome if last else "",
        "defeated_enemies": [e.name for e in repo.defeated_enemies(run.id)],
    }
    context["item_catalog"] = catalog_context(repo, run.id)
    return context
