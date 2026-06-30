"""A deterministic, offline provider.

It requires no API key and lets the whole engine run (and be tested) without a
network. It is intentionally simple: it parses the player's verb for the
interpret step, and emits generic-but-valid structures for generation. Real
flavor and genre accuracy come from the cloud/local providers; the mock just
keeps everything mechanically sound and reproducible.
"""

from __future__ import annotations

import hashlib
import json
import re

from .base import LLMProvider

_DIRECTION_WORDS = {
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "northeast": "ne",
    "northwest": "nw",
    "southeast": "se",
    "southwest": "sw",
    "n": "n",
    "s": "s",
    "e": "e",
    "w": "w",
    "ne": "ne",
    "nw": "nw",
    "se": "se",
    "sw": "sw",
    "up": "n",
    "down": "s",
}

_PLACE_WORDS = [
    "Hollow",
    "Crossing",
    "Reach",
    "Expanse",
    "Threshold",
    "Span",
    "Verge",
    "Quarter",
]
_DESCRIPTOR_WORDS = [
    "Quiet",
    "Shrouded",
    "Weathered",
    "Forgotten",
    "Distant",
    "Gilded",
    "Hollowed",
    "Restless",
]
_ENTITY_WORDS = ["Stranger", "Watcher", "Drifter", "Sentinel", "Forager"]


class MockProvider(LLMProvider):
    name = "mock"

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if "parser for a text RPG" in system:
            return self._interpret(user)
        if "seed the opening" in system:
            return self._seed(user)
        if "generate ONE new location" in system:
            return self._location(user)
        if "generate an NPC's spoken reply" in system:
            return self._dialogue(user)
        # Default: narration (prose, not JSON).
        return self._narrate(user)

    # --- helpers --------------------------------------------------------------
    @staticmethod
    def _player_input(user: str) -> str:
        match = re.search(r"Player input:\s*(.*)", user)
        if match:
            return match.group(1).strip().splitlines()[0].strip()
        return user.strip().splitlines()[0].strip()

    @staticmethod
    def _hash_int(text: str) -> int:
        return int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big")

    def _interpret(self, user: str) -> str:
        text = self._player_input(user).lower()
        tokens = re.findall(r"[a-z']+", text)
        action: dict = {"type": "unknown"}
        if not tokens:
            return json.dumps(action)

        verb = tokens[0]
        rest = " ".join(tokens[1:]).strip()

        if verb in {"look", "examine", "inspect", "l"}:
            action = {"type": "look", "target": rest or None}
        elif verb in {"inventory", "inv", "i", "items"}:
            action = {"type": "inventory"}
        elif "what items" in text or "what do i have" in text or "what am i carrying" in text:
            action = {"type": "inventory"}
        elif verb in {"go", "move", "walk", "head", "travel"} or verb in _DIRECTION_WORDS:
            direction = None
            for tok in tokens:
                if tok in _DIRECTION_WORDS:
                    direction = _DIRECTION_WORDS[tok]
                    break
            action = {"type": "move", "direction": direction}
        elif verb in {"take", "grab", "pick", "get", "loot"}:
            action = {"type": "take", "target": rest.replace("up ", "") or None}
        elif verb in {"talk", "speak", "ask", "greet"}:
            target = rest.replace("to ", "").replace("with ", "")
            action = {"type": "talk", "target": target or None, "text": None}
        elif verb in {"attack", "fight", "hit", "kill", "strike"}:
            action = {"type": "attack", "target": rest or None}
        elif verb in {"equip", "wield", "wear", "don"}:
            action = {"type": "equip", "target": rest.replace("the ", "") or None}
        elif verb in {"use", "apply"}:
            action = {"type": "use", "target": rest or None}
        elif verb in {"say", "shout", "yell"}:
            action = {"type": "say", "text": rest or None}
        return json.dumps(action)

    def _pick(self, seed: str, words: list[str]) -> str:
        return words[self._hash_int(seed) % len(words)]

    def _location(self, user: str) -> str:
        h = str(self._hash_int(user))
        name = f"{self._pick(h + 'd', _DESCRIPTOR_WORDS)} {self._pick(h + 'p', _PLACE_WORDS)}"
        payload = {
            "name": name,
            "region": "world",
            "description": (
                f"A {self._pick(h + 'd', _DESCRIPTOR_WORDS).lower()} place that opens "
                "before you, its details still settling into focus."
            ),
            "facts": [
                {"key": "mood", "value": self._pick(h + "d", _DESCRIPTOR_WORDS).lower()}
            ],
            "entities": [
                {
                    "type": "item",
                    "name": f"Worn {self._pick(h + 'i', ['Token', 'Charm', 'Key'])}",
                    "facts": [{"key": "slot", "value": "misc"}],
                    "stats": [],
                },
            ],
        }
        if self._hash_int(user + "spawn") % 2 == 0:
            payload["entities"].append(
                {
                    "type": "enemy",
                    "name": f"{self._pick(h + 'e', _ENTITY_WORDS)} of {name}",
                    "facts": [{"key": "demeanor", "value": "wary"}],
                    "stats": [{"key": "hp", "value": 10.0}, {"key": "attack", "value": 3.0}],
                }
            )
        else:
            payload["entities"].append(
                {
                    "type": "npc",
                    "name": self._pick(h + "n", _ENTITY_WORDS),
                    "facts": [{"key": "role", "value": "wanderer"}],
                    "stats": [],
                }
            )
        payload["entities"].append(
            {
                "type": "item",
                "name": f"Rusty {self._pick(h + 'w', ['Blade', 'Dagger', 'Axe'])}",
                "facts": [{"key": "slot", "value": "weapon"}],
                "stats": [{"key": "attack", "value": 2.0}],
            }
        )
        return json.dumps(payload)

    def _dialogue(self, user: str) -> str:
        player_says = ""
        match = re.search(r'"player_says":\s*"((?:[^"\\]|\\.)*)"', user)
        if match:
            player_says = match.group(1).replace('\\"', '"')
        history_len = len(re.findall(r'"speaker":\s*"', user))
        player_l = player_says.lower()

        if not player_says and history_len == 0:
            reply = (
                "Welcome, traveler. Princess Sofia was taken to the northern hills. "
                "We need your help."
            )
            facts = [{"key": "quest_hook", "value": "Princess Sofia taken north"}]
        elif "what should" in player_l or "what do" in player_l:
            reply = (
                "Go north to the hills and search for Sofia. "
                "Take the old forest path and stay wary of strangers."
            )
            facts = []
        elif "terrible" in player_l or "oh no" in player_l:
            reply = (
                "I know it is awful, but we cannot delay. "
                "The northern hills are our best lead."
            )
            facts = []
        elif "reward" in player_l or "defeat" in player_l or "killed" in player_l:
            reply = (
                "Very well! Take this reward for your bravery — "
                "ten gold and a pair of healing potions."
            )
            facts = []
            return json.dumps(
                {
                    "npc_reply": reply,
                    "new_facts": facts,
                    "grant_items": [
                        {
                            "name": "Healing Potion",
                            "qty": 2,
                            "facts": [{"key": "slot", "value": "misc"}],
                        }
                    ],
                    "grant_gold": 10,
                }
            )
        else:
            reply = "I hear you. Focus on the northern hills — that is where we must go."
            facts = []

        return json.dumps({"npc_reply": reply, "new_facts": facts})

    def _seed(self, user: str) -> str:
        h = str(self._hash_int(user))
        start_name = f"{self._pick(h + 'd', _DESCRIPTOR_WORDS)} {self._pick(h + 'p', _PLACE_WORDS)}"
        north_name = f"{self._pick(h + 'n1', _DESCRIPTOR_WORDS)} Hills"
        east_name = f"{self._pick(h + 'e1', _PLACE_WORDS)} Trail"
        forest_name = f"{self._pick(h + 'f1', _DESCRIPTOR_WORDS)} Forest"
        cave_name = f"{self._pick(h + 'c1', _PLACE_WORDS)} Caverns"
        payload = {
            "genre": "adventure",
            "item_catalog": [
                {
                    "name": "Traveler's Blade",
                    "description": "A well-worn sword.",
                    "slot": "weapon",
                    "stats": [{"key": "attack", "value": 3.0}],
                },
                {
                    "name": "Healing Potion",
                    "description": "Restores 20 HP.",
                    "slot": "consumable",
                    "stats": [{"key": "heal_hp", "value": 20.0}],
                    "facts": [{"key": "consumable", "value": "true"}],
                },
            ],
            "starting_location": {
                "name": start_name,
                "region": "world",
                "description": (
                    "Your story begins here, the world quietly assembling itself "
                    "around your first steps."
                ),
                "facts": [{"key": "role", "value": "starting point"}],
                "entities": [
                    {
                        "type": "npc",
                        "name": "Guide",
                        "facts": [{"key": "role", "value": "helpful stranger"}],
                        "stats": [],
                    },
                    {
                        "type": "item",
                        "name": "Traveler's Note",
                        "facts": [{"key": "contents", "value": "a vague map sketch"}],
                        "stats": [],
                    },
                ],
            },
            "additional_locations": [
                {
                    "location": {
                        "name": north_name,
                        "region": "world",
                        "description": "Rolling hills stretch under a wide sky.",
                        "entities": [
                            {
                                "type": "enemy",
                                "name": "Hill Bandit",
                                "stats": [
                                    {"key": "hp", "value": 12.0},
                                    {"key": "attack", "value": 4.0},
                                ],
                            }
                        ],
                    },
                    "x": 0,
                    "y": 1,
                },
                {
                    "location": {
                        "name": east_name,
                        "region": "world",
                        "description": "A worn trail leads toward distant trees.",
                        "entities": [
                            {
                                "type": "item",
                                "name": "Healing Potion",
                                "facts": [{"key": "slot", "value": "consumable"}],
                                "stats": [{"key": "heal_hp", "value": 20.0}],
                            }
                        ],
                    },
                    "x": 1,
                    "y": 0,
                },
                {
                    "location": {
                        "name": forest_name,
                        "region": "world",
                        "description": "Ancient trees crowd a mossy path.",
                        "entities": [
                            {
                                "type": "npc",
                                "name": "Forest Scout",
                                "facts": [{"key": "role", "value": "missing scout"}],
                            }
                        ],
                    },
                    "x": 1,
                    "y": 1,
                },
                {
                    "location": {
                        "name": cave_name,
                        "region": "world",
                        "description": "Dark caverns yawn beneath the forest floor.",
                        "entities": [
                            {
                                "type": "enemy",
                                "name": "Cave Wyrm",
                                "stats": [
                                    {"key": "hp", "value": 50.0},
                                    {"key": "attack", "value": 11.0},
                                ],
                            }
                        ],
                    },
                    "x": 2,
                    "y": 1,
                },
            ],
            "initial_connections": [
                {"from_location": start_name, "direction": "n", "to_location": north_name},
                {"from_location": start_name, "direction": "e", "to_location": east_name},
                {"from_location": north_name, "direction": "e", "to_location": forest_name},
                {"from_location": east_name, "direction": "n", "to_location": forest_name},
                {"from_location": forest_name, "direction": "e", "to_location": cave_name},
            ],
            "player_name": "Traveler",
            "player_facts": [{"key": "origin", "value": "unknown"}],
            "player_stats": [
                {"key": "hp", "value": 20.0},
                {"key": "max_hp", "value": 20.0},
                {"key": "attack", "value": 5.0},
            ],
            "starting_items": [
                {
                    "type": "item",
                    "name": "Traveler's Blade",
                    "facts": [
                        {"key": "slot", "value": "weapon"},
                        {"key": "condition", "value": "well-worn"},
                    ],
                    "stats": [{"key": "attack", "value": 3.0}],
                },
            ],
            "opening_quest": (
                f"Search the {north_name} and {forest_name} for signs of the missing scouts."
            ),
        }
        return json.dumps(payload)

    def _narrate(self, user: str) -> str:
        # The outcome-to-narrate block is appended after the context, so the
        # action result's summary is the LAST "summary" field in the prompt.
        matches = re.findall(r'"summary":\s*"((?:[^"\\]|\\.)*)"', user)
        if matches:
            return matches[-1].replace('\\"', '"').replace("\\\\", "\\")
        return "You take in the moment, and the world waits for your next move."
