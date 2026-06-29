"""Deterministic, seeded randomness.

All mechanical randomness in the game flows through a :class:`GameRNG` so that a
run is reproducible from its seed. The LLM provides *content*; the RNG provides
*mechanics* (dice rolls, combat variance, etc.).
"""

from __future__ import annotations

import hashlib
import random
from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")


def seed_from_text(text: str) -> int:
    """Derive a stable 63-bit integer seed from arbitrary text."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


class GameRNG:
    """A thin, explicit wrapper over :class:`random.Random`.

    Using a dedicated class (rather than the global ``random`` module) keeps the
    randomness isolated per run and trivially serializable via :meth:`getstate`.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._random = random.Random(seed)

    def roll(self, sides: int, count: int = 1) -> int:
        """Roll ``count`` dice with ``sides`` faces and return the sum."""
        if sides < 1:
            raise ValueError("dice must have at least 1 side")
        return sum(self._random.randint(1, sides) for _ in range(count))

    def randint(self, low: int, high: int) -> int:
        return self._random.randint(low, high)

    def chance(self, probability: float) -> bool:
        """Return True with the given probability in [0, 1]."""
        return self._random.random() < probability

    def choice(self, items: Sequence[T]) -> T:
        return self._random.choice(items)

    def shuffle(self, items: list[T]) -> None:
        self._random.shuffle(items)

    def sample(self, items: Iterable[T], k: int) -> list[T]:
        return self._random.sample(list(items), k)

    # --- Serialization helpers -------------------------------------------------
    def getstate(self) -> tuple:
        return self._random.getstate()

    def setstate(self, state: tuple) -> None:
        self._random.setstate(state)

    def derive(self, salt: str) -> "GameRNG":
        """Create a child RNG deterministically derived from this one + salt.

        Useful for giving each subsystem (e.g. a specific location's generation)
        its own reproducible stream without disturbing the main sequence.
        """
        child_seed = seed_from_text(f"{self.seed}:{salt}")
        return GameRNG(child_seed)
