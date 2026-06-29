"""NPC dialogue persistence and conversation continuity."""

from __future__ import annotations

from llm_rpg.config import Config
from llm_rpg.engine.engine import Engine, coerce_conversation_action
from llm_rpg.llm.mock_provider import MockProvider
from llm_rpg.state.models import Action, ActionType, EntityType
from llm_rpg.state.repository import Repository


def _setup_npc_scene(repo: Repository, run_id: str, player_id: str) -> str:
    loc_id = repo.entity_location(player_id)
    assert loc_id is not None
    elara = repo.create_entity(run_id, EntityType.npc, "Elara")
    repo.place_entity(run_id, elara.id, loc_id)
    repo.set_fact(run_id, elara.id, "role", "Village Elder")
    repo.commit()
    return elara.id


def test_conversation_log_persists(repo: Repository):
    run = repo.create_run("w", seed=1)
    npc = repo.create_entity(run.id, EntityType.npc, "Elara")
    repo.log_conversation(run.id, npc.id, 1, "player", "Hello")
    repo.log_conversation(run.id, npc.id, 1, "npc", "Welcome.")
    repo.commit()
    history = repo.conversation_with(run.id, npc.id)
    assert len(history) == 2
    assert history[0].speaker == "player"
    assert history[1].text == "Welcome."


def test_coerce_say_to_talk_with_single_npc():
    context = {
        "location": {
            "present_entities": [{"name": "Elara", "type": "npc"}],
        }
    }
    action = Action(type=ActionType.say, text="oh no that's terrible")
    coerced = coerce_conversation_action(action, context)
    assert coerced.type == ActionType.talk
    assert coerced.target == "Elara"
    assert coerced.text == "oh no that's terrible"


def test_coerce_talk_when_npc_named_in_text():
    context = {
        "location": {
            "present_entities": [
                {"name": "Elara", "type": "npc"},
                {"name": "Shopkeeper", "type": "npc"},
            ],
        }
    }
    action = Action(type=ActionType.unknown)
    coerced = coerce_conversation_action(
        action, context, player_text="what should I do, Elara?"
    )
    assert coerced.type == ActionType.talk
    assert coerced.target == "Elara"


def test_talk_persists_npc_reply(seeded_run, repo: Repository, llm: MockProvider, config: Config):
    player_id = seeded_run.player_id
    elara_id = _setup_npc_scene(repo, seeded_run.id, player_id)
    engine = Engine(repo, llm, seeded_run, config)

    out = engine.take_turn("talk to Elara")
    assert out.action_type == "talk"
    assert "Princess Sofia" in out.summary

    history = repo.conversation_with(seeded_run.id, elara_id)
    assert any(h.speaker == "npc" and "Sofia" in h.text for h in history)

    follow_up = engine.take_turn("what should I do, Elara?")
    assert follow_up.action_type == "talk"
    assert "the hills" in follow_up.summary.lower()
    assert len(repo.conversation_with(seeded_run.id, elara_id)) >= 3


def test_say_to_lone_npc_becomes_talk(seeded_run, repo: Repository, llm: MockProvider, config: Config):
    player_id = seeded_run.player_id
    elara_id = _setup_npc_scene(repo, seeded_run.id, player_id)
    engine = Engine(repo, llm, seeded_run, config)

    engine.take_turn("talk to Elara")
    out = engine.take_turn("oh no that's terrible")
    assert out.action_type == "talk"
    assert "northern hills" in out.summary.lower()
    assert len(repo.conversation_with(seeded_run.id, elara_id)) >= 3
