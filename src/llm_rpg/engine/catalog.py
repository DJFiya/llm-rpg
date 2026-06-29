"""World item catalog: canonical definitions seeded once, reused everywhere."""

from __future__ import annotations

import json

from ..state.models import CatalogItemGen, EntityGen, EntityType, FactGen, ItemGrantGen, StatGen
from ..state.repository import Repository
from .items import find_item_by_name, resolve_or_create_item
from .matching import normalize_item_base_name

_DEFAULT_CATALOG: list[CatalogItemGen] = [
    CatalogItemGen(
        name="Healing Potion",
        description="Restores health when consumed.",
        slot="consumable",
        stats=[StatGen(key="heal_hp", value=20.0)],
        facts=[FactGen(key="consumable", value="true")],
    ),
]


def _entry_to_entity_gen(entry: CatalogItemGen) -> EntityGen:
    facts = list(entry.facts)
    if not any(f.key == "slot" for f in facts):
        facts.append(FactGen(key="slot", value=entry.slot))
    if entry.slot == "consumable" and not any(f.key == "consumable" for f in facts):
        facts.append(FactGen(key="consumable", value="true"))
    return EntityGen(
        type=EntityType.item,
        name=entry.name,
        stats=list(entry.stats),
        facts=facts,
    )


def merge_catalog(entries: list[CatalogItemGen]) -> list[CatalogItemGen]:
    """Ensure every run has baseline consumables; dedupe by name."""
    by_name: dict[str, CatalogItemGen] = {
        item.name.strip().lower(): item for item in _DEFAULT_CATALOG
    }
    for entry in entries:
        by_name[entry.name.strip().lower()] = entry
    return list(by_name.values())


def materialize_catalog(repo: Repository, run_id: str, entries: list[CatalogItemGen]) -> None:
    """Create catalog item entities (stats/facts only — not placed yet)."""
    for entry in merge_catalog(entries):
        gen = _entry_to_entity_gen(entry)
        item, _created = resolve_or_create_item(repo, run_id, gen)
        if entry.description:
            repo.set_fact(run_id, item.id, "description", entry.description)
    repo.set_fact(
        run_id,
        run_id,
        "item_catalog",
        json.dumps([entry.model_dump() for entry in merge_catalog(entries)]),
    )


def catalog_context(repo: Repository, run_id: str) -> list[dict]:
    """Compact catalog for LLM prompts (from DB facts + live item stats)."""
    raw = repo.get_fact(run_id, run_id, "item_catalog")
    if raw:
        try:
            entries = json.loads(raw)
            return [
                {
                    "name": e["name"],
                    "slot": e.get("slot", "misc"),
                    "stats": e.get("stats", []),
                    "description": e.get("description", ""),
                }
                for e in entries
            ]
        except json.JSONDecodeError:
            pass
    return _live_catalog_context(repo, run_id)


def _live_catalog_context(repo: Repository, run_id: str) -> list[dict]:
    rows = repo.conn.execute(
        "SELECT id, name FROM entities WHERE run_id = ? AND type = ?",
        (run_id, EntityType.item.value),
    ).fetchall()
    result: list[dict] = []
    for row in rows:
        item_id = row["id"]
        result.append(
            {
                "name": row["name"],
                "slot": repo.get_fact(run_id, item_id, "slot") or "misc",
                "stats": [
                    {"key": key, "value": value}
                    for key, value in repo.get_stats(item_id).items()
                ],
                "description": repo.get_fact(run_id, item_id, "description") or "",
            }
        )
    return result


def catalog_template_for_name(
    repo: Repository, run_id: str, name: str
) -> EntityGen | ItemGrantGen | None:
    """Look up a catalog entry by item name for grants/spawns."""
    base = normalize_item_base_name(name)
    raw = repo.get_fact(run_id, run_id, "item_catalog")
    if raw:
        try:
            for entry in json.loads(raw):
                if entry["name"].strip().lower() == base.lower():
                    return _entry_to_entity_gen(CatalogItemGen.model_validate(entry))
        except json.JSONDecodeError:
            pass
    existing = find_item_by_name(repo, run_id, base)
    if existing is None:
        return None
    stats = [
        StatGen(key=key, value=value)
        for key, value in repo.get_stats(existing.id).items()
    ]
    facts = [
        FactGen(key=f.key, value=f.value)
        for f in repo.facts_for(run_id, existing.id)
    ]
    return EntityGen(type=EntityType.item, name=existing.name, stats=stats, facts=facts)


def grant_spec_for_name(
    repo: Repository, run_id: str, name: str, qty: int = 1
) -> ItemGrantGen:
    """Build a grant using catalog stats when the name is known."""
    template = catalog_template_for_name(repo, run_id, name)
    if template is None:
        return ItemGrantGen(
            name=normalize_item_base_name(name),
            qty=qty,
            facts=[FactGen(key="slot", value="misc")],
        )
    if isinstance(template, ItemGrantGen):
        return template
    return ItemGrantGen(
        name=template.name,
        qty=qty,
        stats=list(template.stats),
        facts=list(template.facts),
    )
