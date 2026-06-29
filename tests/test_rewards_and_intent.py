"""Conversation intent coercion, NPC grants, and enemy death cleanup."""

from __future__ import annotations

from llm_rpg.config import Config
from llm_rpg.engine.engine import Engine, coerce_attack_in_conversation
from llm_rpg.llm.mock_provider import MockProvider
from llm_rpg.state.models import Action, ActionType, EntityType
from llm_rpg.state.repository import Repository


def test_coerce_hypothetical_fight_to_talk():
    context = {
        "interaction": {"focus_npc": "Gorm the Village Elder"},
        "location": {
            "present_entities": [
                {"name": "Gorm the Village Elder", "type": "npc", "conversation": []},
                {"name": "Darkspawn Golem", "type": "enemy"},
            ],
        },
    }
    action = Action(type=ActionType.attack, target="Darkspawn Golem")
    coerced = coerce_attack_in_conversation(
        action,
        context,
        player_text="If I fight the golem will you help me",
    )
    assert coerced.type == ActionType.talk
    assert coerced.target == "Gorm the Village Elder"
    assert "fight the golem" in (coerced.text or "").lower()


def test_imperative_kill_stays_attack():
    context = {
        "interaction": {"focus_npc": "Gorm the Village Elder"},
        "location": {
            "present_entities": [
                {"name": "Gorm the Village Elder", "type": "npc"},
                {"name": "Darkspawn Golem", "type": "enemy"},
            ],
        },
    }
    action = Action(type=ActionType.attack, target="Darkspawn Golem")
    coerced = coerce_attack_in_conversation(
        action, context, player_text="kill golem"
    )
    assert coerced.type == ActionType.attack


def test_dead_enemy_removed_from_room(seeded_run, repo, llm, config: Config):
    loc_id = repo.entity_location(seeded_run.player_id)
    enemy = repo.create_entity(seeded_run.id, EntityType.enemy, "Training Dummy")
    repo.place_entity(seeded_run.id, enemy.id, loc_id)
    repo.set_stat(enemy.id, "hp", 1)
    repo.set_stat(enemy.id, "attack", 0)
    repo.commit()

    engine = Engine(repo, llm, seeded_run, config)
    out = engine.take_turn("attack the Training Dummy")
    assert out.action_type == "attack"
    assert repo.get_entity(enemy.id).status == "dead"
    present = repo.entities_at(loc_id, exclude_id=seeded_run.player_id)
    assert all(e.id != enemy.id for e in present)


def test_enemy_drops_item_on_death(seeded_run, repo, llm, config: Config):
    loc_id = repo.entity_location(seeded_run.player_id)
    guard = repo.create_entity(seeded_run.id, EntityType.enemy, "Prison Guard")
    repo.place_entity(seeded_run.id, guard.id, loc_id)
    repo.set_fact(seeded_run.id, guard.id, "drop_item", "Iron Key")
    repo.set_stat(guard.id, "hp", 1)
    repo.set_stat(guard.id, "attack", 0)
    repo.commit()

    engine = Engine(repo, llm, seeded_run, config)
    out = engine.take_turn("attack the Prison Guard")
    assert "Iron Key" in out.summary
    items = [
        e for e in repo.entities_at(loc_id) if e.type == EntityType.item
    ]
    assert any("Iron Key" in e.name for e in items)


def test_npc_reward_adds_to_inventory(repo: Repository, llm: MockProvider, config: Config):
    from llm_rpg.game import new_game

    run = repo.create_run("w", seed=1)
    new_game.seed_world(repo, llm, run, retries=1)
    run = repo.get_run(run.id)
    loc_id = repo.entity_location(run.player_id)

    gorm = repo.create_entity(run.id, EntityType.npc, "Elara")
    repo.place_entity(run.id, gorm.id, loc_id)
    golem = repo.create_entity(run.id, EntityType.enemy, "Golem")
    repo.set_entity_status(golem.id, "dead")
    repo.commit()

    engine = Engine(repo, llm, run, config)
    engine.take_turn("talk to Elara")
    out = engine.take_turn("since I defeated the golem can I get a reward")
    assert out.action_type == "talk"
    assert "You receive:" in out.summary

    inv_names = [item.name for item, _qty in repo.inventory(run.player_id)]
    assert any("Healing Potion" in name for name in inv_names)
    gold = repo.inventory(run.player_id)
    total_gold = sum(
        qty for item, qty in gold if "gold" in item.name.lower()
    )
    assert total_gold >= 10
