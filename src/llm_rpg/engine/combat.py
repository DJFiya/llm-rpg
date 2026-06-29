"""Deterministic combat resolution.

Combat outcomes are computed entirely by the engine using the run's seeded RNG,
never by the LLM. The narrator is later told what happened (the numbers) and may
only describe it. This keeps fights fair, reproducible, and hallucination-free.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..rng import GameRNG
from ..state.repository import Repository


@dataclass
class CombatResult:
    attacker_name: str
    defender_name: str
    damage_to_defender: int
    damage_to_attacker: int
    defender_hp: float
    attacker_hp: float
    defender_dead: bool
    attacker_dead: bool


def _attack_damage(rng: GameRNG, base_attack: float) -> int:
    """Base attack plus a small d6 variance, floored at 1."""
    variance = rng.roll(6) - 3  # -2..+3
    return max(1, int(round(base_attack + variance)))


def resolve_attack(
    repo: Repository,
    rng: GameRNG,
    attacker_id: str,
    defender_id: str,
) -> CombatResult:
    """Resolve one exchange: attacker hits defender, survivors retaliate."""
    attacker = repo.get_entity(attacker_id)
    defender = repo.get_entity(defender_id)
    assert attacker is not None and defender is not None

    atk_attack = repo.get_stat(attacker_id, "attack") or 1.0
    def_attack = repo.get_stat(defender_id, "attack") or 0.0
    atk_hp = repo.get_stat(attacker_id, "hp")
    def_hp = repo.get_stat(defender_id, "hp")
    # Entities without explicit hp are treated as fragile (1 hp).
    atk_hp = 1.0 if atk_hp is None else atk_hp
    def_hp = 1.0 if def_hp is None else def_hp

    dmg_to_def = _attack_damage(rng, atk_attack)
    def_hp = max(0.0, def_hp - dmg_to_def)
    defender_dead = def_hp <= 0

    dmg_to_atk = 0
    if not defender_dead and def_attack > 0:
        dmg_to_atk = _attack_damage(rng, def_attack)
        atk_hp = max(0.0, atk_hp - dmg_to_atk)
    attacker_dead = atk_hp <= 0

    repo.set_stat(defender_id, "hp", def_hp)
    repo.set_stat(attacker_id, "hp", atk_hp)
    if defender_dead:
        repo.set_entity_status(defender_id, "dead")
    if attacker_dead:
        repo.set_entity_status(attacker_id, "dead")

    return CombatResult(
        attacker_name=attacker.name,
        defender_name=defender.name,
        damage_to_defender=dmg_to_def,
        damage_to_attacker=dmg_to_atk,
        defender_hp=def_hp,
        attacker_hp=atk_hp,
        defender_dead=defender_dead,
        attacker_dead=attacker_dead,
    )
