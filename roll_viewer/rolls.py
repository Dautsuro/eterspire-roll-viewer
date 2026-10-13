"""Works out the roll level of every stat on an item from its values and its quality.

Weapons and armor have 3 stats with 5 levels each (1 Lowest, 2 Low, 3 Neutral, 4 High, 5 Highest) and
``quality = floor(100 * sum of levels / 15)``. Bonus Attack Speed, Strength and Vitality are read from their
value (0 or hidden = Neutral, negative = Low/Lowest). Damage and HP change between game updates, so their
level is whatever is left once the other two are subtracted from the quality.

Rings have Strength and Vitality with 7 levels each (-3, -2, -1, none, Low, Mid, High) and
``quality = floor(100 * sum of levels / 14)``; both are read from the ring table.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "rolls.json"

HP, DAMAGE, ATTACK_SPEED, BONUS_ATTACK_SPEED, VITALITY, STRENGTH = (
    "hp", "damage", "attack_speed", "bonus_attack_speed", "vitality", "strength"
)
WEAPON, ARMOR, RING = "weapon", "armor", "ring"

GEAR_STATS = {WEAPON: (DAMAGE, BONUS_ATTACK_SPEED, VITALITY), ARMOR: (HP, BONUS_ATTACK_SPEED, STRENGTH)}
RING_STATS = (STRENGTH, VITALITY)
GEAR_NAMES = {1: "Lowest", 2: "Low", 3: "Neutral", 4: "High", 5: "Highest"}
RING_NAMES = {1: "-3", 2: "-2", 3: "-1", 4: "None", 5: "Low", 6: "Mid", 7: "High"}


@dataclass
class Item:
    kind: str  # WEAPON, ARMOR or RING
    tier: int | None = None
    quality: int | None = None  # percent shown in the game
    excellent: bool = False
    # Base value of each stat line (the upgrade bonus "+ 37" is not included). A stat that isn't listed
    # is a neutral roll; None means the line is there but its value could not be read.
    stats: dict[str, int | None] = field(default_factory=dict)


@dataclass
class Roll:
    levels: tuple[int, ...]  # every level that fits; one when it's certain
    max_level: int
    names: dict[int, str]
    consistent: bool = True  # False when the levels don't add up to the quality shown

    @property
    def certain(self) -> bool:
        return len(self.levels) == 1 and self.consistent

    @property
    def text(self) -> str:
        if not self.levels:
            return "?"
        lo, hi = self.levels[0], self.levels[-1]
        if lo == hi:
            core = str(lo)
        elif list(self.levels) == list(range(lo, hi + 1)):
            core = f"{lo}-{hi}"
        else:
            core = ",".join(map(str, self.levels))
        return f"{core}/{self.max_level}" + ("" if self.consistent else "?")

    @property
    def name(self) -> str:
        return self.names[self.levels[0]] if len(self.levels) == 1 else ""

    @property
    def fraction(self) -> float:
        """0 for the worst roll .. 1 for the best (average when uncertain), for colouring."""
        if not self.levels:
            return 0.5
        return (sum(self.levels) / len(self.levels) - 1) / (self.max_level - 1)


def load_data(path: Path = DATA_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _nearest(value: float, candidates: dict[int, float]) -> int:
    """The level whose value is closest to ``value`` (compared as ratios, so 39 vs 49/81 picks 49)."""
    return min(candidates, key=lambda level: abs(math.log(abs(value) / abs(candidates[level]))))


def _sums_for_quality(quality: int, levels_total: int) -> set[int]:
    """Level sums that the game would show as ``quality`` percent (it rounds down)."""
    sums = {s for s in range(levels_total + 1) if math.floor(100 * s / levels_total + 1e-9) == quality}
    return sums or {s for s in range(levels_total + 1) if round(100 * s / levels_total) == quality}


def _signed_gear_level(stat: str, value: int | None, item: Item, gear: dict) -> set[int]:
    if value is None:
        return {1, 2, 3, 4, 5}
    if value == 0:
        return {3}
    rarity = "excellent" if item.excellent else "normal"
    if stat == BONUS_ATTACK_SPEED:
        high, highest = gear[BONUS_ATTACK_SPEED][item.kind][rarity]
    else:
        tier = item.tier if item.tier is not None else gear["reference_tier"]
        scale = gear["tier_multiplier"] ** (tier - gear["reference_tier"])
        high, highest = (v * scale for v in gear[stat][rarity])
    level = _nearest(value, {4: high, 5: highest})
    return {level} if value > 0 else {6 - level}


def gear_rolls(item: Item, data: dict) -> dict[str, Roll]:
    gear = data["gear"]
    main, *signed = GEAR_STATS[item.kind]
    options = {stat: _signed_gear_level(stat, item.stats.get(stat, 0), item, gear) for stat in signed}
    # Excellent gear has only the Low/Mid/High damage and HP values, which are levels 3-5.
    main_options = [{3, 4, 5}, {1, 2, 3, 4, 5}] if item.excellent else [{1, 2, 3, 4, 5}]

    order = [main, *signed]
    combos = []
    sums = _sums_for_quality(item.quality, 15) if item.quality is not None else None
    for candidates in main_options:
        options[main] = candidates
        combos = [c for c in itertools.product(*(sorted(options[s]) for s in order)) if sums is None or sum(c) in sums]
        if combos:
            break

    rolls = {}
    for i, stat in enumerate(order):
        if combos:
            levels = tuple(sorted({c[i] for c in combos}))
            rolls[stat] = Roll(levels, 5, GEAR_NAMES)
        else:  # the quality doesn't fit: show what the values alone say and flag it
            levels = tuple(sorted(options[stat])) if stat != main else ()
            rolls[stat] = Roll(levels, 5, GEAR_NAMES, consistent=False)
    return rolls


def _ring_row(table: dict, tier: int | None) -> list:
    tiers = sorted(int(t) for t in table)
    if tier is None:
        tier = tiers[-1]
    return table[str(min(tiers, key=lambda t: (abs(t - tier), -t)))]


def ring_rolls(item: Item, data: dict) -> dict[str, Roll]:
    rarity = "excellent" if item.excellent else "normal"
    row = _ring_row(data["rings"][rarity], item.tier)
    levels_of_row = [5, 6, 7] if item.excellent else [1, 2, 3, 5, 6, 7]
    candidates = {lv: v for lv, v in zip(levels_of_row, row) if v is not None}

    rolls = {}
    for stat in RING_STATS:
        value = item.stats.get(stat, 0)
        if value is None:
            levels = tuple(range(1, 8))
        elif value == 0:
            levels = (4,)
        else:
            same_sign = {lv: v for lv, v in candidates.items() if (v > 0) == (value > 0)}
            levels = (_nearest(value, same_sign),) if same_sign else ()
        rolls[stat] = Roll(levels, 7, RING_NAMES)

    if item.quality is not None and all(len(r.levels) == 1 for r in rolls.values()):
        total = sum(r.levels[0] for r in rolls.values())
        if total not in _sums_for_quality(item.quality, 14):
            for roll in rolls.values():
                roll.consistent = False
    return rolls


def compute_rolls(item: Item, data: dict) -> dict[str, Roll]:
    """Roll of each stat that counts toward quality (Attack Speed is fixed and left out)."""
    if item.kind == RING:
        return ring_rolls(item, data)
    return gear_rolls(item, data)
