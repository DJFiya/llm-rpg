"""Starting inventory from world seed."""

from __future__ import annotations

from llm_rpg.config import Config
from llm_rpg.engine.engine import Engine
from llm_rpg.llm.mock_provider import MockProvider
from llm_rpg.rng import seed_from_text
from llm_rpg.game import new_game


def test_seed_gives_starting_items(repo, llm: MockProvider):
    prompt = "A test realm."
    run = repo.create_run(prompt, seed=seed_from_text(prompt))
    new_game.seed_world(repo, llm, run, retries=1)
    run = repo.get_run(run.id)
    inv = repo.inventory(run.player_id)
    names = [item.name for item, _qty in inv]
    assert "Traveler's Blade" in names


def test_inventory_turn_is_grounded(repo, llm: MockProvider, config: Config):
    prompt = "A test realm."
    run = repo.create_run(prompt, seed=seed_from_text(prompt))
    new_game.seed_world(repo, llm, run, retries=1)
    run = repo.get_run(run.id)
    engine = Engine(repo, llm, run, config)
    out = engine.take_turn("what items do i have")
    assert out.action_type == "inventory"
    assert "Traveler's Blade" in out.narration
    assert "Effective attack" in out.narration
    assert "Equipped: weapon" in out.narration
    assert out.narration == out.summary
