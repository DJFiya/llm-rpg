"""Initial world map is seeded with connected locations at game start."""

from __future__ import annotations

from llm_rpg.engine import world_gen
from llm_rpg.engine.memory import build_context, world_map_context
from llm_rpg.rng import seed_from_text


def test_seed_creates_connected_initial_map(seeded_run, repo):
    locations = repo.all_locations(seeded_run.id)
    assert len(locations) >= 5

    start_id = repo.entity_location(seeded_run.player_id)
    north = repo.connection_in_direction(start_id, "n")
    assert north is not None

    world_map = world_map_context(repo, seeded_run)
    assert world_map["location_count"] >= 5
    start_node = next(
        n for n in world_map["locations"] if n["name"] == repo.get_location(start_id).name
    )
    assert any(e["direction"] == "north" for e in start_node["exits"])


def test_lazy_generation_still_works(seeded_run, repo, llm):
    """Moving into unmapped territory still generates new locations."""
    start_id = repo.entity_location(seeded_run.player_id)
    before = len(repo.all_locations(seeded_run.id))

    # West is not on the mock initial map.
    assert repo.connection_in_direction(start_id, "w") is None
    start = repo.get_location(start_id)
    dest, created = world_gen.generate_adjacent_location(
        repo, llm, seeded_run, start, "w", retries=1
    )
    assert created is True
    assert len(repo.all_locations(seeded_run.id)) == before + 1
    assert dest.x == start.x - 1


def test_world_map_in_turn_context(seeded_run, repo):
    ctx = build_context(repo, seeded_run, memory_window=8)
    assert "world_map" in ctx
    assert ctx["world_map"]["location_count"] >= 5
