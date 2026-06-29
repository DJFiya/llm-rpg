"""Consistency guardrails applied to LLM-generated content before it is stored.

These checks are the code-side half of the anti-hallucination strategy: even if
the model proposes something contradictory or duplicated, it never reaches the
world state. Functions here are pure-ish helpers that operate against the repo.
"""

from __future__ import annotations

from ..state.repository import Repository


class ConsistencyError(ValueError):
    """Raised when generated content cannot be reconciled with existing state."""


def unique_entity_name(repo: Repository, run_id: str, name: str) -> str:
    """Return a name guaranteed not to collide with an existing entity.

    Entity names are unique per run (enforced by the schema). Rather than reject
    a useful generation outright, we disambiguate by appending a numeric suffix.
    """
    base = name.strip() or "Unnamed"
    candidate = base
    suffix = 2
    while repo.find_entity_by_name(run_id, candidate) is not None:
        candidate = f"{base} ({suffix})"
        suffix += 1
    return candidate


def unique_location_name(repo: Repository, run_id: str, name: str) -> str:
    base = name.strip() or "Unnamed Place"
    existing = {loc.name.lower() for loc in repo.all_locations(run_id)}
    candidate = base
    suffix = 2
    while candidate.lower() in existing:
        candidate = f"{base} ({suffix})"
        suffix += 1
    return candidate


def assert_alive(repo: Repository, entity_id: str) -> None:
    entity = repo.get_entity(entity_id)
    if entity is None:
        raise ConsistencyError("referenced entity does not exist")
    if entity.status == "dead":
        raise ConsistencyError(f"{entity.name} is dead and cannot act or be targeted")


def coords_free(repo: Repository, run_id: str, region: str, x: int, y: int) -> bool:
    return repo.location_at(run_id, region, x, y) is None
