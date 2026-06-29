"""Map generation must stay spatially consistent and bidirectionally traversable."""

from __future__ import annotations

from llm_rpg.engine import world_gen
from llm_rpg.llm.mock_provider import MockProvider
from llm_rpg.rng import seed_from_text
from llm_rpg.state.repository import Repository


def _new_run(repo: Repository):
    return repo.create_run("mapping world", seed=seed_from_text("map"))


def test_move_creates_adjacent_with_correct_coords(repo: Repository, llm: MockProvider):
    run = _new_run(repo)
    start = repo.create_location(run.id, "Start", x=0, y=0)
    dest, created = world_gen.generate_adjacent_location(
        repo, llm, run, start, "n", retries=1
    )
    assert created is True
    assert (dest.x, dest.y) == (0, 1)  # north => +y


def test_reverse_connection_exists(repo: Repository, llm: MockProvider):
    run = _new_run(repo)
    start = repo.create_location(run.id, "Start", x=0, y=0)
    dest, _ = world_gen.generate_adjacent_location(repo, llm, run, start, "e", retries=1)
    # Forward edge east, reverse edge west.
    fwd = repo.connection_in_direction(start.id, "e")
    rev = repo.connection_in_direction(dest.id, "w")
    assert fwd.to_location == dest.id
    assert rev.to_location == start.id


def test_no_duplicate_location_on_collision(repo: Repository, llm: MockProvider):
    run = _new_run(repo)
    start = repo.create_location(run.id, "Start", x=0, y=0)
    # Go north then south: should return to start, not create a 3rd node.
    north, _ = world_gen.generate_adjacent_location(repo, llm, run, start, "n", retries=1)
    back, created = world_gen.generate_adjacent_location(
        repo, llm, run, north, "s", retries=1
    )
    assert created is False
    assert back.id == start.id
    assert len(repo.all_locations(run.id)) == 2


def test_loop_links_existing_location(repo: Repository, llm: MockProvider):
    """A square loop (n, e, s, w) must close back onto the start."""
    run = _new_run(repo)
    start = repo.create_location(run.id, "Start", x=0, y=0)
    n, _ = world_gen.generate_adjacent_location(repo, llm, run, start, "n", retries=1)
    ne, _ = world_gen.generate_adjacent_location(repo, llm, run, n, "e", retries=1)
    e, _ = world_gen.generate_adjacent_location(repo, llm, run, ne, "s", retries=1)
    closed, created = world_gen.generate_adjacent_location(
        repo, llm, run, e, "w", retries=1
    )
    assert created is False
    assert closed.id == start.id
    assert len(repo.all_locations(run.id)) == 4
