"""The seeded RNG must be reproducible and deterministic."""

from __future__ import annotations

from llm_rpg.rng import GameRNG, seed_from_text


def test_same_seed_same_sequence():
    a = GameRNG(1234)
    b = GameRNG(1234)
    assert [a.roll(20) for _ in range(50)] == [b.roll(20) for _ in range(50)]


def test_different_seeds_diverge():
    a = GameRNG(1)
    b = GameRNG(2)
    assert [a.roll(100) for _ in range(50)] != [b.roll(100) for _ in range(50)]


def test_seed_from_text_is_stable():
    assert seed_from_text("hello world") == seed_from_text("hello world")
    assert seed_from_text("a") != seed_from_text("b")


def test_derive_is_deterministic():
    parent = GameRNG(99)
    c1 = parent.derive("combat")
    c2 = GameRNG(99).derive("combat")
    assert c1.seed == c2.seed
