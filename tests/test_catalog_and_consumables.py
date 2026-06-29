"""Item catalog seeding, consumable use, and enemy gift restrictions."""

from __future__ import annotations

from llm_rpg.config import Config
from llm_rpg.engine.catalog import catalog_context, materialize_catalog, merge_catalog
from llm_rpg.engine.consumables import use_consumable
from llm_rpg.engine.engine import Engine
from llm_rpg.engine.rewards import apply_dialogue_grants
from llm_rpg.llm.mock_provider import MockProvider
from llm_rpg.state.models import CatalogItemGen, DialogueGen, EntityType, ItemGrantGen, StatGen
from llm_rpg.state.repository import Repository


def test_seed_materializes_item_catalog(seeded_run, repo: Repository):
    catalog = catalog_context(repo, seeded_run.id)
    assert any(item["name"] == "Healing Potion" for item in catalog)
    assert any(
        stat.get("key") == "heal_hp"
        for item in catalog
        if item["name"] == "Healing Potion"
        for stat in item.get("stats", [])
    )


def test_enemy_dialogue_cannot_grant_items(repo: Repository):
    run = repo.create_run("w", seed=1)
    materialize_catalog(
        repo,
        run.id,
        merge_catalog(
            [
                CatalogItemGen(
                    name="Healing Potion",
                    slot="consumable",
                    stats=[StatGen(key="heal_hp", value=20.0)],
                )
            ]
        ),
    )
    player = repo.create_entity(run.id, EntityType.player, "Hero")
    goblin = repo.create_entity(run.id, EntityType.enemy, "Goblin Pack Leader")
    reply = DialogueGen(
        npc_reply="I shall give you this Potion of Healing.",
        grant_items=[ItemGrantGen(name="Healing Potion", qty=1)],
    )
    granted = apply_dialogue_grants(
        repo,
        run.id,
        player.id,
        reply,
        defeated_enemies=[],
        player_said="ask what your business is",
        speaker_id=goblin.id,
    )
    assert granted == []


def test_use_healing_potion_restores_hp(seeded_run, repo, llm: MockProvider, config: Config):
    materialize_catalog(
        repo,
        seeded_run.id,
        merge_catalog(
            [
                CatalogItemGen(
                    name="Healing Potion",
                    slot="consumable",
                    stats=[StatGen(key="heal_hp", value=20.0)],
                )
            ]
        ),
    )
    player_id = seeded_run.player_id
    repo.set_stat(player_id, "hp", 5.0)
    repo.set_stat(player_id, "max_hp", 20.0)

    from llm_rpg.engine.items import add_item_to_inventory
    from llm_rpg.state.models import EntityGen

    add_item_to_inventory(
        repo,
        seeded_run.id,
        player_id,
        EntityGen(type=EntityType.item, name="Healing Potion"),
        qty=1,
    )
    repo.commit()

    engine = Engine(repo, llm, seeded_run, config)
    out = engine.take_turn("use healing potion")
    assert out.action_type == "use"
    assert "recover" in out.summary.lower()
    assert repo.get_stat(player_id, "hp") == 20.0
