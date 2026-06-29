"""The turn orchestrator: interpret -> validate/apply -> narrate.

This is the only place the three LLM roles are sequenced. Crucially, the LLM
output for interpretation is validated into an :class:`Action`, the *engine*
decides and applies the outcome, and only then does the narrator describe the
engine's ground-truth result.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

from ..config import Config
from ..llm.base import LLMError, LLMProvider
from ..llm.prompts import INTERPRET_SYSTEM, NARRATE_SYSTEM
from ..rng import GameRNG
from ..state.models import Action, ActionType, Run
from ..state.repository import Repository
from . import memory
from .actions import HANDLERS, ActionResult, TurnContext


@dataclass
class TurnOutput:
    action_type: str
    summary: str
    narration: str
    player_dead: bool = False


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
        user = (
            f"Player input: {player_text}\n\n"
            "Context (use these exact names where relevant):\n"
            f"{json.dumps(context, ensure_ascii=False)}"
        )
        try:
            return self.llm.generate_json(
                INTERPRET_SYSTEM,
                user,
                Action,
                retries=self.config.json_repair_retries,
            )
        except LLMError:
            return Action(type=ActionType.unknown, text=player_text)

    # --- Phase 3: narrate -----------------------------------------------------
    def narrate(self, result: ActionResult, context: dict) -> str:
        result_payload = dataclasses.asdict(result)
        user = (
            "Context (ground truth facts):\n"
            f"{json.dumps(context, ensure_ascii=False)}\n\n"
            "Outcome to narrate (do not change these facts):\n"
            f"{json.dumps(result_payload, ensure_ascii=False)}"
        )
        try:
            text = self.llm.complete(NARRATE_SYSTEM, user).strip()
        except LLMError:
            text = ""
        return text or result.summary

    # --- Full turn ------------------------------------------------------------
    def take_turn(self, player_text: str) -> TurnOutput:
        context = memory.build_context(self.repo, self.run, self.config.memory_window)
        action = self.interpret(player_text, context)

        handler = HANDLERS.get(action.type.value, HANDLERS["unknown"])
        ctx = TurnContext(
            repo=self.repo,
            llm=self.llm,
            run=self.run,
            rng=self.rng,
            retries=self.config.json_repair_retries,
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

        narration = self.narrate(result, context)
        player_dead = bool(result.details.get("player_dead"))
        return TurnOutput(
            action_type=result.action_type,
            summary=result.summary,
            narration=narration,
            player_dead=player_dead,
        )
