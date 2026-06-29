"""Deterministic combat resolution.

Combat uses effective attack (base + equipped weapon) and effective defense
( equipped armor reduces incoming damage). All numbers come from the database.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..rng import GameRNG
from ..state.repository import Repository
from .equipment import effective_attack, effective_defense


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
    attacker_attack_used: float
    defender_attack_used: float
    defender_defense_used: float
    attacker_defense_used: float


def _attack_damage(rng: GameRNG, base_attack: float) -> int:
    """Base attack plus a small d6 variance, floored at 1."""
    variance = rng.roll(6) - 3  # -2..+3
    return max(1, int(round(base_attack + variance)))


def _apply_defense(damage: int, defense: float) -> int:
    """Armor shaves off defense points; always at least 1 on a hit."""
    return max(1, damage - int(round(defense)))


def resolve_attack(
    repo: Repository,
    rng: GameRNG,
    attacker_id: str,
    defender_id: str,
    *,
    run_id: str,
) -> CombatResult:
    """Resolve one exchange: attacker hits defender, survivors retaliate."""
    attacker = repo.get_entity(attacker_id)
    defender = repo.get_entity(defender_id)
    assert attacker is not None and defender is not None

    atk_attack = effective_attack(repo, run_id, attacker_id)
    def_attack = effective_attack(repo, run_id, defender_id)
    if def_attack <= 1 and not repo.get_equipped(defender_id, "weapon"):
        def_attack = repo.get_stat(defender_id, "attack") or 0.0

    atk_defense = effective_defense(repo, run_id, attacker_id)
    def_defense = effective_defense(repo, run_id, defender_id)

    atk_hp = repo.get_stat(attacker_id, "hp")
    def_hp = repo.get_stat(defender_id, "hp")
    atk_hp = 1.0 if atk_hp is None else atk_hp
    def_hp = 1.0 if def_hp is None else def_hp

    raw_to_def = _attack_damage(rng, atk_attack)
    dmg_to_def = _apply_defense(raw_to_def, def_defense)
    def_hp = max(0.0, def_hp - dmg_to_def)
    defender_dead = def_hp <= 0

    dmg_to_atk = 0
    raw_to_atk = 0
    if not defender_dead and def_attack > 0:
        raw_to_atk = _attack_damage(rng, def_attack)
        dmg_to_atk = _apply_defense(raw_to_atk, atk_defense)
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
        attacker_attack_used=atk_attack,
        defender_attack_used=def_attack,
        defender_defense_used=def_defense,
        attacker_defense_used=atk_defense,
    )
