"""Shared test fixtures."""

from __future__ import annotations

import pytest

from llm_rpg.config import Config
from llm_rpg.llm.mock_provider import MockProvider
from llm_rpg.rng import seed_from_text
from llm_rpg.state import db
from llm_rpg.state.repository import Repository


@pytest.fixture
def repo() -> Repository:
    conn = db.connect_memory()
    return Repository(conn)


@pytest.fixture
def llm() -> MockProvider:
    return MockProvider()


@pytest.fixture
def config() -> Config:
    return Config(provider="mock", memory_window=8, json_repair_retries=1)


@pytest.fixture
def seeded_run(repo: Repository, llm: MockProvider):
    """A run with a seeded opening world, ready to play."""
    from llm_rpg.game import new_game

    prompt = "A quiet test realm of stone and mist."
    run = repo.create_run(world_prompt=prompt, seed=seed_from_text(prompt))
    new_game.seed_world(repo, llm, run, retries=1)
    run = repo.get_run(run.id)
    return run
