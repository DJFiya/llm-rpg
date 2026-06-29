"""Consistency guardrails for generated content."""

from __future__ import annotations

import pytest

from llm_rpg.engine import consistency
from llm_rpg.engine.consistency import ConsistencyError
from llm_rpg.state.models import EntityType
from llm_rpg.state.repository import Repository


def test_unique_entity_name_disambiguates(repo: Repository):
    run = repo.create_run("w", seed=1)
    repo.create_entity(run.id, EntityType.npc, "Wolf")
    name = consistency.unique_entity_name(repo, run.id, "Wolf")
    assert name == "Wolf (2)"


def test_unique_location_name_disambiguates(repo: Repository):
    run = repo.create_run("w", seed=1)
    repo.create_location(run.id, "Cave", x=0, y=0)
    name = consistency.unique_location_name(repo, run.id, "Cave")
    assert name == "Cave (2)"


def test_assert_alive_rejects_dead(repo: Repository):
    run = repo.create_run("w", seed=1)
    enemy = repo.create_entity(run.id, EntityType.enemy, "Ghoul")
    repo.set_entity_status(enemy.id, "dead")
    with pytest.raises(ConsistencyError):
        consistency.assert_alive(repo, enemy.id)
