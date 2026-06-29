"""Grounded narration policy tests."""

from __future__ import annotations

from llm_rpg.config import Config
from llm_rpg.engine.actions import ActionResult
from llm_rpg.engine.engine import Engine, coerce_inventory_action
from llm_rpg.engine.narration import build_narrate_context, should_use_llm_narration
from llm_rpg.llm.mock_provider import MockProvider
from llm_rpg.state.models import Action, ActionType


def test_coerce_inventory_phrases():
    action = Action(type=ActionType.unknown)
    coerced = coerce_inventory_action(action, "what items do i have")
    assert coerced.type == ActionType.inventory


def test_skip_llm_for_failed_take():
    result = ActionResult(
        "take", "There is no rock here to take.", {"failed": True}
    )
    assert should_use_llm_narration(result) is False


def test_skip_llm_for_talk():
    result = ActionResult(
        "talk",
        "Elara replies: 'Hello.'",
        {"npc_reply": "Hello."},
    )
    assert should_use_llm_narration(result) is False


def test_llm_only_for_look_and_move():
    assert should_use_llm_narration(ActionResult("look", "You look.")) is True
    assert should_use_llm_narration(ActionResult("move", "You go north.")) is True
    assert should_use_llm_narration(ActionResult("attack", "You hit.")) is False
    assert should_use_llm_narration(ActionResult("inventory", "You carry: sword.")) is False


def test_engine_narrate_attack_uses_summary_not_llm(config: Config, repo, llm, seeded_run):
    """Attack narration must echo exact engine numbers, never LLM prose."""

    class _FailIfCalled(MockProvider):
        def complete(self, system, user, *, json_mode=False):
            raise AssertionError("LLM narrate should not run for attack")

    engine = Engine(repo, _FailIfCalled(), seeded_run, config)
    result = ActionResult(
        "attack",
        "You strike Frost Wyrm for 7 damage. Frost Wyrm has 3 HP left and hits back for 2. You have 18 HP remaining.",
        {"player_hp": 18, "defender_hp": 3, "damage_dealt": 7, "damage_taken": 2},
    )
    text = engine.narrate(result, {})
    assert text == result.summary
    assert "7 damage" in text
    assert "18 HP" in text


def test_narrate_context_strips_world_prompt_and_lists_allowed_entities():
    full = {
        "world_prompt": "A vast epic with princesses",
        "location": {
            "name": "Cave",
            "description": "A damp cave.",
            "exits": [{"direction": "south", "to": "Field"}],
            "present_entities": [
                {"name": "Rusty Key", "type": "item", "status": "active"},
            ],
        },
    }
    result = ActionResult("look", "Cave. A damp cave. Exits: south.")
    ctx = build_narrate_context(full, result)
    assert "world_prompt" not in ctx
    assert ctx["allowed_entity_names"] == ["Rusty Key"]
    assert ctx["present_entities"] == [{"name": "Rusty Key", "type": "item"}]
