"""Pydantic models for world-state rows and LLM structured outputs.

These models are the validation boundary: nothing reaches the database without
passing through one of them, and every LLM response is parsed into one of the
``*Gen`` models so malformed or hallucinated structures are rejected early.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    player = "player"
    npc = "npc"
    enemy = "enemy"
    item = "item"
    faction = "faction"


# --- Stored rows --------------------------------------------------------------

class Run(BaseModel):
    id: str
    world_prompt: str
    genre: str | None = None
    seed: int
    turn: int = 0
    player_id: str | None = None
    created_at: str
    updated_at: str


class Location(BaseModel):
    id: str
    run_id: str
    name: str
    region: str = "world"
    x: int
    y: int
    description: str = ""
    discovered: bool = True


class Connection(BaseModel):
    run_id: str
    from_location: str
    to_location: str
    direction: str


class Entity(BaseModel):
    id: str
    run_id: str
    type: EntityType
    name: str
    status: str = "active"


class Fact(BaseModel):
    run_id: str
    subject_id: str
    key: str
    value: str


class Quest(BaseModel):
    id: str
    run_id: str
    title: str
    summary: str = ""
    status: str = "active"


class ActionLogEntry(BaseModel):
    id: int | None = None
    run_id: str
    turn: int
    location_id: str | None = None
    action_type: str
    player_text: str = ""
    outcome: str = ""
    created_at: str


class ConversationEntry(BaseModel):
    turn: int
    speaker: str
    text: str


# --- LLM structured outputs ---------------------------------------------------

class ActionType(str, Enum):
    look = "look"
    move = "move"
    take = "take"
    talk = "talk"
    attack = "attack"
    inventory = "inventory"
    equip = "equip"
    use = "use"
    say = "say"
    unknown = "unknown"


class Action(BaseModel):
    """The interpreted player intent. Produced by the LLM, validated here."""

    type: ActionType
    target: str | None = Field(
        default=None,
        description="Name of the entity/item/NPC the action applies to, if any.",
    )
    direction: str | None = Field(
        default=None,
        description="Movement direction for 'move': n/s/e/w/ne/nw/se/sw.",
    )
    text: str | None = Field(
        default=None,
        description="Free-form speech for 'say'/'talk'.",
    )


class StatGen(BaseModel):
    key: str
    value: float


class FactGen(BaseModel):
    key: str
    value: str


class EntityGen(BaseModel):
    """An entity proposed by the LLM during lazy world generation."""

    type: EntityType
    name: str
    facts: list[FactGen] = Field(default_factory=list)
    stats: list[StatGen] = Field(default_factory=list)


class LocationGen(BaseModel):
    """A location proposed by the LLM when the player enters new territory."""

    name: str
    description: str
    region: str = "world"
    facts: list[FactGen] = Field(default_factory=list)
    entities: list[EntityGen] = Field(default_factory=list)


class SeedGen(BaseModel):
    """The opening world the LLM seeds from the player's world prompt."""

    genre: str
    starting_location: LocationGen
    player_name: str
    player_facts: list[FactGen] = Field(default_factory=list)
    player_stats: list[StatGen] = Field(default_factory=list)
    starting_items: list[EntityGen] = Field(
        default_factory=list,
        description="Items the player begins with (type must be item).",
    )
    opening_quest: str | None = None


class ItemGrantGen(BaseModel):
    """An item the NPC gives the player this turn (materialized into inventory)."""

    name: str
    qty: int = Field(default=1, ge=1)
    facts: list[FactGen] = Field(default_factory=list)
    stats: list[StatGen] = Field(default_factory=list)


class DialogueGen(BaseModel):
    """An NPC's spoken reply, validated before it becomes ground truth."""

    npc_reply: str
    new_facts: list[FactGen] = Field(
        default_factory=list,
        description="Optional durable facts revealed in this exchange.",
    )
    grant_items: list[ItemGrantGen] = Field(
        default_factory=list,
        description="Items the NPC actually gives the player this turn.",
    )
    grant_gold: int = Field(
        default=0,
        ge=0,
        description="Gold coins added to the player's purse when the NPC pays them.",
    )
