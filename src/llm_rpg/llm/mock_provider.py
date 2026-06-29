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
        elif verb in {"use", "apply", "equip"}:
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
                    "facts": [{"key": "condition", "value": "weathered"}],
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
        else:
            reply = "I hear you. Focus on the northern hills — that is where we must go."
            facts = []

        return json.dumps({"npc_reply": reply, "new_facts": facts})

    def _seed(self, user: str) -> str:
        h = str(self._hash_int(user))
        start_name = f"{self._pick(h + 'd', _DESCRIPTOR_WORDS)} {self._pick(h + 'p', _PLACE_WORDS)}"
        payload = {
            "genre": "adventure",
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
            "player_name": "Traveler",
            "player_facts": [{"key": "origin", "value": "unknown"}],
            "player_stats": [
                {"key": "hp", "value": 20.0},
                {"key": "attack", "value": 5.0},
            ],
            "starting_items": [
                {
                    "type": "item",
                    "name": "Traveler's Blade",
                    "facts": [{"key": "condition", "value": "well-worn"}],
                    "stats": [],
                },
            ],
            "opening_quest": "Discover what lies beyond the first horizon.",
        }
        return json.dumps(payload)

    def _narrate(self, user: str) -> str:
        # The outcome-to-narrate block is appended after the context, so the
        # action result's summary is the LAST "summary" field in the prompt.
        matches = re.findall(r'"summary":\s*"((?:[^"\\]|\\.)*)"', user)
        if matches:
            return matches[-1].replace('\\"', '"').replace("\\\\", "\\")
        return "You take in the moment, and the world waits for your next move."
