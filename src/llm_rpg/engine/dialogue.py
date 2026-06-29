"""Grounded NPC dialogue: generate, validate, and persist spoken lines."""

from __future__ import annotations

import json

from ..llm.base import LLMProvider
from ..llm.prompts import DIALOGUE_SYSTEM
from ..state.models import DialogueGen, Entity, Run
from ..state.repository import Repository


def generate_npc_reply(
    repo: Repository,
    llm: LLMProvider,
    run: Run,
    npc: Entity,
    player_said: str | None,
    *,
    turn: int,
    world_context: dict,
    retries: int = 2,
) -> DialogueGen:
    """Ask the LLM for an NPC reply grounded in facts and prior conversation."""
    history = repo.conversation_with(run.id, npc.id, limit=20)
    npc_facts = {f.key: f.value for f in repo.facts_for(run.id, npc.id)}
    payload = {
        "world_prompt": run.world_prompt,
        "genre": run.genre,
        "npc": {
            "name": npc.name,
            "facts": npc_facts,
        },
        "conversation_history": [
            {"speaker": entry.speaker, "text": entry.text} for entry in history
        ],
        "player_says": player_said or "",
        "active_quests": world_context.get("active_quests", []),
        "location": world_context.get("location"),
    }
    user = (
        f"Generate {npc.name}'s spoken reply.\n\n"
        f"Context:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    return llm.generate_json(DIALOGUE_SYSTEM, user, DialogueGen, retries=retries)


def persist_dialogue(
    repo: Repository,
    run_id: str,
    npc_id: str,
    turn: int,
    player_said: str | None,
    reply: DialogueGen,
) -> None:
    """Save the exchange and any new durable facts revealed by the NPC."""
    if player_said:
        repo.log_conversation(run_id, npc_id, turn, "player", player_said)
    repo.log_conversation(run_id, npc_id, turn, "npc", reply.npc_reply)
    for fact in reply.new_facts:
        repo.set_fact(run_id, npc_id, fact.key, fact.value)
