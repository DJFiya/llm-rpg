"""Item deduplication, grant guards, and fuzzy NPC matching."""

from __future__ import annotations

from llm_rpg.config import Config
from llm_rpg.engine.engine import Engine
from llm_rpg.engine.items import find_item_by_name, resolve_or_create_item
from llm_rpg.engine.matching import best_fuzzy_match
from llm_rpg.engine.rewards import apply_dialogue_grants, npc_reply_indicates_transfer
from llm_rpg.llm.mock_provider import MockProvider
from llm_rpg.state.models import DialogueGen, EntityGen, EntityType, ItemGrantGen
from llm_rpg.state.repository import Repository


def test_items_reuse_existing_name(repo: Repository):
    run = repo.create_run("w", seed=1)
    gen = EntityGen(type=EntityType.item, name="Forsaken Sword")
    first, created_first = resolve_or_create_item(repo, run.id, gen)
    second, created_second = resolve_or_create_item(repo, run.id, gen)
    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    assert first.name == "Forsaken Sword"
    legacy = find_item_by_name(repo, run.id, "Forsaken Sword (2)")
    assert legacy is not None and legacy.id == first.id


def test_starting_item_and_ground_item_share_entity(seeded_run, repo: Repository):
    loc_id = repo.entity_location(seeded_run.player_id)
    gen = EntityGen(
        type=EntityType.item,
        name="Traveler's Blade",
        facts=[{"key": "slot", "value": "weapon"}],
        stats=[{"key": "attack", "value": 2.0}],
    )
    from llm_rpg.engine.items import place_item_at_location

    placed = place_item_at_location(repo, seeded_run.id, loc_id, gen)
    assert placed is None
    assert find_item_by_name(repo, seeded_run.id, "Traveler's Blade") is not None


def test_npc_reply_indicates_transfer():
    assert npc_reply_indicates_transfer("Very well! Take this reward for your bravery.")
    assert not npc_reply_indicates_transfer("Ah, you've got a third Forsaken Sword?")


def test_commentary_grants_are_ignored(repo: Repository):
    run = repo.create_run("w", seed=1)
    player = repo.create_entity(run.id, EntityType.player, "Hero")
    reply = DialogueGen(
        npc_reply="Ah, you've got a third Forsaken Sword?",
        grant_items=[ItemGrantGen(name="Forsaken Sword", qty=2)],
    )
    granted = apply_dialogue_grants(
        repo,
        run.id,
        player.id,
        reply,
        defeated_enemies=[],
        player_said="is that a third forsaken sword",
    )
    assert granted == []
    assert repo.inventory(player.id) == []


def test_inferred_grant_from_here_is_phrase(repo: Repository):
    run = repo.create_run("w", seed=1)
    player = repo.create_entity(run.id, EntityType.player, "Hero")
    reply = DialogueGen(
        npc_reply=(
            "I think it would be wise for me to provide you with something to aid "
            "in your quest. Here is a Potion of Healing - may it help you in the "
            "battles ahead."
        ),
    )
    granted = apply_dialogue_grants(
        repo,
        run.id,
        player.id,
        reply,
        defeated_enemies=[],
        player_said=(
            "I have no gold for the villagers. Can you provide me with something "
            "magical to defeat these goblins"
        ),
    )
    assert granted == ["Potion of Healing"]
    assert any(
        "Potion of Healing" in item.name
        for item, _qty in repo.inventory(player.id)
    )


def test_mentioning_gold_does_not_block_npc_gift(repo: Repository):
    run = repo.create_run("w", seed=1)
    player = repo.create_entity(run.id, EntityType.player, "Hero")
    reply = DialogueGen(
        npc_reply="Here is a Potion of Healing - use it well.",
        grant_items=[ItemGrantGen(name="Potion of Healing", qty=1)],
    )
    granted = apply_dialogue_grants(
        repo,
        run.id,
        player.id,
        reply,
        defeated_enemies=[],
        player_said="I have no gold but I need help",
    )
    assert granted == ["Potion of Healing"]


def test_fuzzy_npc_name_match():
    assert best_fuzzy_match("ragmar", ["Rigmar the Wanderer"]) == "Rigmar the Wanderer"


def test_typo_npc_talk(seeded_run, repo, llm: MockProvider, config: Config):
    loc_id = repo.entity_location(seeded_run.player_id)
    rigmar = repo.create_entity(seeded_run.id, EntityType.npc, "Rigmar the Wanderer")
    repo.place_entity(seeded_run.id, rigmar.id, loc_id)
    repo.commit()

    engine = Engine(repo, llm, seeded_run, config)
    out = engine.take_turn("is that a third forsaken sword i ask ragmar")
    assert out.action_type == "talk"
    assert "Rigmar" in out.summary
    assert "You receive:" not in out.summary
