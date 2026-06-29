"""Repository CRUD and lookup behavior."""

from __future__ import annotations

from llm_rpg.state.models import EntityType
from llm_rpg.state.repository import Repository


def test_run_and_turn_advance(repo: Repository):
    run = repo.create_run("test world", seed=42)
    assert run.turn == 0
    assert repo.advance_turn(run.id) == 1
    assert repo.advance_turn(run.id) == 2
    assert repo.get_run(run.id).turn == 2


def test_facts_are_lookups_not_constants(repo: Repository):
    run = repo.create_run("w", seed=1)
    repo.set_fact(run.id, "world", "capital", "Highmoor")
    assert repo.get_fact(run.id, "world", "capital") == "Highmoor"
    # Upsert overwrites rather than duplicating.
    repo.set_fact(run.id, "world", "capital", "Ashfall")
    assert repo.get_fact(run.id, "world", "capital") == "Ashfall"
    assert len(repo.facts_for(run.id, "world")) == 1


def test_stats_and_inventory(repo: Repository):
    run = repo.create_run("w", seed=1)
    hero = repo.create_entity(run.id, EntityType.player, "Hero")
    sword = repo.create_entity(run.id, EntityType.item, "Sword")
    repo.set_stat(hero.id, "hp", 30)
    assert repo.get_stat(hero.id, "hp") == 30
    repo.add_to_inventory(hero.id, sword.id, 1)
    inv = repo.inventory(hero.id)
    assert len(inv) == 1 and inv[0][0].name == "Sword"


def test_entity_name_unique_per_run(repo: Repository):
    run = repo.create_run("w", seed=1)
    repo.create_entity(run.id, EntityType.npc, "Guard")
    found = repo.find_entity_by_name(run.id, "guard")  # case-insensitive
    assert found is not None and found.name == "Guard"
