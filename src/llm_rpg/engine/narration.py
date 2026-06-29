"""Grounded narration: when to call the LLM and what facts it may use."""

from __future__ import annotations

from .actions import ActionResult


def should_use_llm_narration(result: ActionResult) -> bool:
    """Only look/move get LLM prose. Everything else uses the engine summary."""
    if result.details.get("failed"):
        return False
    return result.action_type in {"look", "move"}


def build_narrate_context(full_context: dict, result: ActionResult) -> dict:
    """Minimal, grounded facts for the narrator — no world prompt or quest fluff."""
    location = full_context.get("location") or {}
    present = location.get("present_entities", [])
    payload: dict = {
        "location_name": location.get("name"),
        "location_description": location.get("description", ""),
        "exits": location.get("exits", []),
        "present_entities": [
            {"name": e.get("name"), "type": e.get("type")} for e in present
        ],
        "allowed_entity_names": [e.get("name") for e in present if e.get("name")],
        "outcome": {
            "action_type": result.action_type,
            "summary": result.summary,
            "failed": bool(result.details.get("failed")),
        },
    }
    if result.details.get("npc_reply"):
        payload["outcome"]["npc_reply"] = result.details["npc_reply"]
    return payload
