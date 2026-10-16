"""Updates the gear values in roll_viewer/data/rolls.json from the "Bonus stats by tier" spreadsheet.

    python tools/import_bonus_stats.py data-sources/gear-bonus-stats.xlsx   (needs openpyxl)

Each cell lists every roll worst to best, like "-49 / -30 / 0 / 30 / 49" (monster drops) or "0 / 30 / 49"
(boss gear and Excellent). The two best are kept as [high, highest]; a missing one ("-") is stored as null.
Bonus Attack Speed is checked to be the same everywhere, since the app treats it as the same for every tier.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import openpyxl

DATA = Path(__file__).resolve().parents[1] / "roll_viewer" / "data" / "rolls.json"
COLUMNS = {  # spreadsheet header -> (stat, rarity)
    "Armor STR (normal)": ("strength", "normal"),
    "Armor STR (Ex.)": ("strength", "excellent"),
    "Weapon VIT (normal)": ("vitality", "normal"),
    "Weapon VIT (Ex.)": ("vitality", "excellent"),
}
BONUS_ATTACK_SPEED = {  # header -> the High/Highest values the app uses
    "Armor AS (normal)": [1, 2], "Armor AS (Ex.)": [3, 4], "Weapon AS (normal)": [5, 10], "Weapon AS (Ex.)": [7, 12],
}


def positive_rolls(cell: str) -> list[int | None]:
    """'-3 / -2 / 0 / 2 / 3' -> [2, 3]; '0 / 4 / -' -> [4, None]; '-1 / 0 / 1' -> [None, 1] (only one known)."""
    values = [v.strip().rstrip("%") for v in str(cell).split("/")]
    after_zero = values[values.index("0") + 1:] if "0" in values else values
    rolls = [int(v) if re.fullmatch(r"-?\d+", v) else None for v in after_zero]
    rolls = [v if v is None or v > 0 else None for v in rolls]
    return ([None] * (2 - len(rolls)) + rolls)[-2:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("xlsx", type=Path)
    args = parser.parse_args()

    sheet = openpyxl.load_workbook(args.xlsx, data_only=True)["Bonus stats by tier"]
    rows = list(sheet.iter_rows(values_only=True))
    header = list(rows[0])
    tables: dict[str, dict[str, dict[str, list]]] = {}
    problems = []
    for row in rows[1:]:
        if row[0] is None:
            continue
        tier, name = str(int(row[0])), row[1]
        for column, expected in BONUS_ATTACK_SPEED.items():
            if positive_rolls(row[header.index(column)]) != expected:
                problems.append(f"{name}: {column} is {row[header.index(column)]}, not ... / {expected[0]} / {expected[1]}")
        for column, (stat, rarity) in COLUMNS.items():
            rolls = positive_rolls(row[header.index(column)])
            known = tables.setdefault(stat, {}).setdefault(rarity, {})
            if tier in known and known[tier] != rolls:
                problems.append(f"Tier {tier} {column}: {name} has {rolls}, another set has {known[tier]}")
            known.setdefault(tier, rolls)

    data = json.loads(DATA.read_text(encoding="utf-8"))
    for stat, rarities in tables.items():
        data["gear"][stat] = {rarity: dict(sorted(values.items(), key=lambda kv: int(kv[0])))
                              for rarity, values in rarities.items()}
    text = json.dumps(data, indent=1)
    text = re.sub(r"\[\s+([^\[\]{}]*?)\s+\]", lambda m: "[" + re.sub(r"\s+", " ", m.group(1)) + "]", text)
    DATA.write_text(text + "\n", encoding="utf-8", newline="\n")
    for stat, rarities in tables.items():
        print(stat, {rarity: len(values) for rarity, values in rarities.items()}, "tiers")
    if problems:
        print("\nCheck these:", *problems, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
