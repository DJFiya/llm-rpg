"""The turn orchestrator: interpret -> validate/apply -> narrate.

This is the only place the three LLM roles are sequenced. Crucially, the LLM
output for interpretation is validated into an :class:`Action`, the *engine*
decides and applies the outcome, and only then does the narrator describe the
engine's ground-truth result.
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass

from ..config import Config
from ..llm.base import LLMError, LLMProvider
from ..llm.prompts import INTERPRET_SYSTEM, NARRATE_SYSTEM
from ..rng import GameRNG
from ..state.models import Action, ActionType, Run
from ..state.repository import Repository
from . import memory
from .actions import HANDLERS, ActionResult, TurnContext
from .matching import best_fuzzy_match, extract_name_hint
from .narration import build_narrate_context, should_use_llm_narration

_QUESTION_MARKERS = (
    "?",
    "will you",
    "would you",
    "could you",
    "can you",
    "if i ",
    "if we ",
    "should i",
    "do you",
    "are you",
    "what if",
    "how would",
    "help me",
)

_IMPERATIVE_ATTACK = (
    "attack ",
    "kill ",
    "strike ",
    "fight the",
    "fight ",
    "hit ",
)


def _looks_like_question(text: str) -> bool:
    t = text.strip().lower()
    if "?" in t:
        return True
    if any(marker in t for marker in _QUESTION_MARKERS):
        return True
    return bool(
        re.match(
            r"^(what|why|how|when|where|who|which|if|will|would|can|could|should|do|does|did|are|is)\b",
            t,
        )
    )


def _conversation_focus(context: dict) -> str | None:
    interaction = context.get("interaction") or {}
    focus = interaction.get("focus_npc")
    if focus:
        return focus

    location = context.get("location") or {}
    npcs = [e for e in location.get("present_entities", []) if e.get("type") == "npc"]
    with_convo = [n for n in npcs if n.get("conversation")]
    if len(with_convo) == 1:
        return with_convo[0]["name"]
    if len(npcs) == 1:
        return npcs[0]["name"]
    return None


def coerce_attack_in_conversation(
    action: Action, context: dict, player_text: str = ""
) -> Action:
    """Hypothetical combat questions to an NPC are talk, not attack."""
    if action.type != ActionType.attack:
        return action
    text = (player_text or action.text or "").strip()
    if not text:
        return action

    text_l = text.lower()
    if not _looks_like_question(text_l):
        return action
    if any(text_l.startswith(v) or text_l == v.strip() for v in _IMPERATIVE_ATTACK):
        return action

    focus = _conversation_focus(context)
    if focus:
        return Action(type=ActionType.talk, target=focus, text=text)

    location = context.get("location") or {}
    npcs = [e for e in location.get("present_entities", []) if e.get("type") == "npc"]
    if len(npcs) == 1:
        return Action(type=ActionType.talk, target=npcs[0]["name"], text=text)
    return action


@dataclass
class TurnOutput:
    action_type: str
    summary: str
    narration: str
    player_dead: bool = False


def coerce_conversation_action(
    action: Action, context: dict, player_text: str = ""
) -> Action:
    """Route free-form speech at a present NPC to talk instead of say/unknown."""
    text = (action.text or action.target or player_text or "").strip()
    location = context.get("location") or {}
    npcs = [
        e for e in location.get("present_entities", []) if e.get("type") == "npc"
    ]
    if not npcs:
        return action
    names = [npc["name"] for npc in npcs]

    if action.type == ActionType.talk:
        target = action.target or ""
        utterance = (action.text or player_text or "").strip()
        if target not in names:
            matched = best_fuzzy_match(
                extract_name_hint(utterance) or target or utterance, names
            )
            if matched:
                spoken = (action.text or player_text or "").strip() or None
                return Action(
                    type=ActionType.talk,
                    target=matched,
                    text=spoken,
                )
        return action

    if action.type not in {ActionType.say, ActionType.unknown}:
        return action
    if not text:
        return action

    text_l = text.lower()
    for npc in npcs:
        name = npc["name"]
        name_l = name.lower()
        first = name.split()[0].lower()
        if name_l in text_l or (len(first) > 2 and first in text_l):
            return Action(type=ActionType.talk, target=name, text=text)

    matched = best_fuzzy_match(extract_name_hint(text) or text, names)
    if matched:
        return Action(type=ActionType.talk, target=matched, text=text)

    if len(npcs) == 1:
        return Action(type=ActionType.talk, target=npcs[0]["name"], text=text)

    # Multiple NPCs: continue with whoever the player was just speaking to.
    for npc in npcs:
        if npc.get("conversation"):
            return Action(type=ActionType.talk, target=npc["name"], text=text)

    return action


_INVENTORY_PHRASES = (
    "what items",
    "what do i have",
    "what do i carry",
    "what am i carrying",
    "my items",
    "my inventory",
    "show inventory",
    "check inventory",
    "do i have anything",
)


def coerce_inventory_action(
    action: Action, player_text: str = ""
) -> Action:
    """Route natural inventory questions to the inventory handler."""
    if action.type == ActionType.inventory:
        return action
    text = player_text.strip().lower()
    if text and any(phrase in text for phrase in _INVENTORY_PHRASES):
        return Action(type=ActionType.inventory)
    return action


class Engine:
    def __init__(
        self,
        repo: Repository,
        llm: LLMProvider,
        run: Run,
        config: Config,
    ) -> None:
        self.repo = repo
        self.llm = llm
        self.run = run
        self.config = config
        self.rng = GameRNG(run.seed)
        # Fast-forward the RNG so resuming a save doesn't repeat the same rolls.
        for _ in range(run.turn):
            self.rng.roll(6)

    # --- Phase 1: interpret ---------------------------------------------------
    def interpret(self, player_text: str, context: dict) -> Action:
        interpret_ctx = {
            "interaction": context.get("interaction", {}),
            "location": {
                "name": (context.get("location") or {}).get("name"),
                "present_entities": (context.get("location") or {}).get(
                    "present_entities", []
                ),
                "exits": (context.get("location") or {}).get("exits", []),
            },
            "player": {
                "name": (context.get("player") or {}).get("name"),
                "inventory": (context.get("player") or {}).get("inventory", []),
            },
            "recent_events": context.get("recent_events", [])[-3:],
            "active_quests": context.get("active_quests", []),
        }
        user = (
            f"Player input: {player_text}\n\n"
            "Context (use these exact names where relevant):\n"
            f"{json.dumps(interpret_ctx, ensure_ascii=False)}"
        )
        try:
            action = self.llm.generate_json(
                INTERPRET_SYSTEM,
                user,
                Action,
                retries=self.config.json_repair_retries,
            )
        except LLMError:
            action = Action(type=ActionType.unknown, text=player_text)
        return coerce_inventory_action(
            coerce_attack_in_conversation(
                coerce_conversation_action(action, context, player_text),
                context,
                player_text,
            ),
            player_text,
        )

    # --- Phase 3: narrate -----------------------------------------------------
    def narrate(self, result: ActionResult, context: dict) -> str:
        if not should_use_llm_narration(result):
            return result.summary

        narrate_ctx = build_narrate_context(context, result)
        result_payload = dataclasses.asdict(result)
        user = (
            "Ground truth (use ONLY these facts):\n"
            f"{json.dumps(narrate_ctx, ensure_ascii=False)}\n\n"
            "Full outcome (do not change):\n"
            f"{json.dumps(result_payload, ensure_ascii=False)}"
        )
        try:
            text = self.llm.complete(NARRATE_SYSTEM, user).strip()
        except LLMError:
            text = ""
        return text or result.summary

    def grounded_location(self) -> dict | None:
        """Current location facts for the status bar (always from the database)."""
        if not self.run.player_id:
            return None
        loc_id = self.repo.entity_location(self.run.player_id)
        if not loc_id:
            return None
        return memory.location_context(self.repo, self.run, loc_id)

    # --- Full turn ------------------------------------------------------------
    def take_turn(self, player_text: str) -> TurnOutput:
        context = memory.build_context(self.repo, self.run, self.config.memory_window)
        action = self.interpret(player_text, context)

        handler = HANDLERS.get(action.type.value, HANDLERS["unknown"])
        next_turn = self.run.turn + 1
        ctx = TurnContext(
            repo=self.repo,
            llm=self.llm,
            run=self.run,
            rng=self.rng,
            retries=self.config.json_repair_retries,
            turn=next_turn,
            world_context=context,
        )
        result = handler(ctx, action)

        turn = self.repo.advance_turn(self.run.id)
        self.run.turn = turn
        location_id = (
            self.repo.entity_location(self.run.player_id)
            if self.run.player_id
            else None
        )
        self.repo.log_action(
            run_id=self.run.id,
            turn=turn,
            action_type=result.action_type,
            player_text=player_text,
            outcome=result.summary,
            location_id=location_id,
        )
        self.repo.commit()

        post_context = memory.build_context(
            self.repo, self.run, self.config.memory_window
        )
        narration = self.narrate(result, post_context)
        player_dead = bool(result.details.get("player_dead"))
        return TurnOutput(
            action_type=result.action_type,
            summary=result.summary,
            narration=narration,
            player_dead=player_dead,
        )
