"""Equipment mechanics: equip, effective stats, combat bonuses."""

from __future__ import annotations

from llm_rpg.config import Config
from llm_rpg.engine.combat import resolve_attack
from llm_rpg.engine.engine import Engine
from llm_rpg.engine.equipment import effective_attack, effective_defense
from llm_rpg.game import new_game
from llm_rpg.llm.mock_provider import MockProvider
from llm_rpg.rng import GameRNG, seed_from_text
from llm_rpg.state.models import EntityType


def _seeded(repo, llm):
    prompt = "Equipment test realm."
    run = repo.create_run(prompt, seed=seed_from_text(prompt))
    new_game.seed_world(repo, llm, run, retries=1)
    return repo.get_run(run.id)


def test_starting_weapon_is_equipped(repo, llm: MockProvider):
    run = _seeded(repo, llm)
    weapon_id = repo.get_equipped(run.player_id, "weapon")
    assert weapon_id is not None
    weapon = repo.get_entity(weapon_id)
    assert weapon is not None and "Blade" in weapon.name


def test_effective_attack_includes_weapon(repo, llm: MockProvider):
    run = _seeded(repo, llm)
    base = repo.get_stat(run.player_id, "attack") or 0
    eff = effective_attack(repo, run.id, run.player_id)
    assert eff > base


def test_equip_changes_effective_attack(repo, llm: MockProvider, config: Config):
    run = _seeded(repo, llm)
    loc_id = repo.entity_location(run.player_id)
    sword = repo.create_entity(run.id, EntityType.item, "Iron Sword")
    repo.set_fact(run.id, sword.id, "slot", "weapon")
    repo.set_stat(sword.id, "attack", 5)
    repo.place_entity(run.id, sword.id, loc_id)
    repo.commit()

    engine = Engine(repo, llm, run, config)
    engine.take_turn("take iron sword")
    out = engine.take_turn("equip iron sword")
    assert out.action_type == "equip"
    assert "Effective attack: 10" in out.summary  # 5 base + 5 sword

    eff = effective_attack(repo, run.id, run.player_id)
    assert eff == 10


def test_armor_reduces_incoming_damage(repo, llm: MockProvider):
    run = _seeded(repo, llm)
    player = run.player_id
    shield = repo.create_entity(run.id, EntityType.item, "Wooden Shield")
    repo.set_fact(run.id, shield.id, "slot", "armor")
    repo.set_stat(shield.id, "defense", 3)
    repo.add_to_inventory(player, shield.id, 1)
    repo.equip(player, "armor", shield.id)
    repo.set_stat(player, "hp", 20)
    repo.set_stat(player, "attack", 5)

    goblin = repo.create_entity(run.id, EntityType.enemy, "Goblin")
    repo.set_stat(goblin.id, "hp", 50)
    repo.set_stat(goblin.id, "attack", 8)

    rng = GameRNG(999)
    assert effective_defense(repo, run.id, player) == 3

    result = resolve_attack(
        repo, rng, goblin.id, player, run_id=run.id
    )
    assert result.damage_to_attacker <= 6
