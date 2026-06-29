"""End-to-end turn flow with the mock provider (offline integration test)."""

from __future__ import annotations

from llm_rpg.config import Config
from llm_rpg.engine.engine import Engine
from llm_rpg.llm.mock_provider import MockProvider
from llm_rpg.state.models import EntityType
from llm_rpg.state.repository import Repository


def _engine(repo: Repository, llm: MockProvider, run, config: Config) -> Engine:
    return Engine(repo, llm, run, config)


def test_seed_creates_player_and_location(seeded_run, repo: Repository):
    assert seeded_run.player_id is not None
    player = repo.get_entity(seeded_run.player_id)
    assert player is not None and player.type == EntityType.player
    # Player has combat-critical stats guaranteed.
    assert repo.get_stat(player.id, "hp") is not None
    assert repo.get_stat(player.id, "attack") is not None
    # Player is placed in a starting location.
    assert repo.entity_location(seeded_run.player_id) is not None


def test_look_then_move(seeded_run, repo, llm, config):
    engine = _engine(repo, llm, seeded_run, config)
    look = engine.take_turn("look around")
    assert look.action_type == "look"
    assert look.narration

    before = len(repo.all_locations(seeded_run.id))
    move = engine.take_turn("go north")
    assert move.action_type == "move"
    after = len(repo.all_locations(seeded_run.id))
    assert after == before + 1  # a new location was generated


def test_turn_is_logged_and_advances(seeded_run, repo, llm, config):
    engine = _engine(repo, llm, seeded_run, config)
    engine.take_turn("look")
    run = repo.get_run(seeded_run.id)
    assert run.turn == 1
    recent = repo.recent_actions(run.id, 10)
    assert len(recent) == 1
    assert recent[0].action_type == "look"


def test_combat_is_deterministic_and_persistent(repo, llm, config):
    """Same seed -> identical combat outcome; HP changes persist."""
    from llm_rpg.engine import combat
    from llm_rpg.rng import GameRNG

    def run_fight() -> float:
        run = repo.create_run("battle", seed=777)
        hero = repo.create_entity(run.id, EntityType.player, "Hero")
        repo.set_stat(hero.id, "hp", 30)
        repo.set_stat(hero.id, "attack", 5)
        goblin = repo.create_entity(run.id, EntityType.enemy, "Goblin")
        repo.set_stat(goblin.id, "hp", 8)
        repo.set_stat(goblin.id, "attack", 2)
        rng = GameRNG(777)
        result = combat.resolve_attack(repo, rng, hero.id, goblin.id, run_id=run.id)
        return result.damage_to_defender

    first = run_fight()
    second = run_fight()
    assert first == second  # deterministic from seed


def test_attack_kills_and_blocks_reattack(seeded_run, repo, llm, config):
    # Place a weak enemy next to the player and attack until dead.
    loc_id = repo.entity_location(seeded_run.player_id)
    enemy = repo.create_entity(seeded_run.id, EntityType.enemy, "Training Dummy")
    repo.place_entity(seeded_run.id, enemy.id, loc_id)
    repo.set_stat(enemy.id, "hp", 1)
    repo.set_stat(enemy.id, "attack", 0)
    repo.commit()

    engine = _engine(repo, llm, seeded_run, config)
    out = engine.take_turn("attack the Training Dummy")
    assert out.action_type == "attack"
    assert repo.get_entity(enemy.id).status == "dead"

    # Attacking a corpse is rejected as inconsistent.
    out2 = engine.take_turn("attack the Training Dummy")
    assert "already dead" in out2.summary.lower()
