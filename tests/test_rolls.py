import pytest

from roll_viewer.rolls import (
    ARMOR, BONUS_ATTACK_SPEED as BAS, DAMAGE, HP, RING, STRENGTH, VITALITY, WEAPON, Item, Roll, compute_rolls,
    gear_values, load_data,
)

DATA = load_data()


def levels(item):
    return {stat: roll.levels for stat, roll in compute_rolls(item, DATA).items()}


@pytest.mark.parametrize(
    "item, expected",
    [
        # Ominous Fire Staff (Excellent) +10, from the "Current" side of a comparison
        (Item(WEAPON, 18, 86, True, {DAMAGE: 1805, BAS: 7, VITALITY: 181}), {DAMAGE: (5,), BAS: (4,), VITALITY: (4,)}),
        # Rhodonite Thunder Staff: Vitality +0 shows as a neutral roll
        (Item(WEAPON, 16, 73, False, {DAMAGE: 1127, BAS: 5, VITALITY: 0}), {DAMAGE: (4,), BAS: (4,), VITALITY: (3,)}),
        # Ominous Thread Boots +5: the example from the request, (3 + 4 + 5) / 15 = 80%
        (Item(ARMOR, 18, 80, False, {HP: 1620, BAS: 1, STRENGTH: 81}), {HP: (3,), BAS: (4,), STRENGTH: (5,)}),
        # Rhodonite Thread Cowl +5: no Bonus Attack Speed line means neutral
        (Item(ARMOR, 16, 60, False, {HP: 960, STRENGTH: 64}), {HP: (1,), BAS: (3,), STRENGTH: (5,)}),
        # Rhodonite Thread Gown (Top)
        (Item(ARMOR, 16, 80, False, {HP: 3840, BAS: 2, STRENGTH: 39}), {HP: (3,), BAS: (5,), STRENGTH: (4,)}),
        # Topaz Thread Gown (Top) +1
        (Item(ARMOR, 15, 46, False, {HP: 2532, BAS: -2, STRENGTH: 57}), {HP: (1,), BAS: (1,), STRENGTH: (5,)}),
        # Null Gauntlets / Null Helm +10, Tier 22: values grow much faster than x1.125 per tier after Tier 18.
        # Their HP 3630 and 4538 are Neutral and Highest of the same base (x1.25), which confirms these rolls.
        (Item(ARMOR, 22, 73, False, {HP: 3630, STRENGTH: 182}), {HP: (3,), BAS: (3,), STRENGTH: (5,)}),
        (Item(ARMOR, 22, 80, False, {HP: 4538, STRENGTH: 109}), {HP: (5,), BAS: (3,), STRENGTH: (4,)}),
        # Rhodonite Fire Staff: Lowest Bonus Attack Speed and Vitality
        (Item(WEAPON, 16, 40, False, {DAMAGE: 1127, BAS: -10, VITALITY: -320}), {DAMAGE: (4,), BAS: (1,), VITALITY: (1,)}),
        # Spiderfang Gauntlets, Tier 4: Strength 0 / 3 / 4, so +3 is High, as the quality of both pairs confirms
        (Item(ARMOR, 4, 73, False, {HP: 88, BAS: 1, STRENGTH: 0}), {HP: (4,), BAS: (4,), STRENGTH: (3,)}),
        (Item(ARMOR, 4, 86, False, {HP: 88, BAS: 2, STRENGTH: 3}), {HP: (4,), BAS: (5,), STRENGTH: (4,)}),
        (Item(ARMOR, 4, 93, False, {HP: 88, BAS: 2, STRENGTH: 4}), {HP: (4,), BAS: (5,), STRENGTH: (5,)}),
        # Tier 1: the wiki only knows Strength's best value, so the quality tells High from Highest
        (Item(ARMOR, 1, 86, False, {HP: 10, BAS: 2, STRENGTH: 1}), {HP: (3, 4), BAS: (5,), STRENGTH: (4, 5)}),
        # Tier XVI Amber Ring (Excellent) +5: Mid strength, no vitality, (6 + 4) / 14 = 71%
        (Item(RING, 16, 71, True, {STRENGTH: 116}), {STRENGTH: (6,), VITALITY: (4,)}),
    ],
)
def test_known_items(item, expected):
    assert levels(item) == expected
    assert all(roll.consistent for roll in compute_rolls(item, DATA).values())


def test_low_rolls_are_negative():
    item = Item(ARMOR, 18, 40, False, {HP: 1620, BAS: -1, STRENGTH: -81})
    assert levels(item) == {HP: (3,), BAS: (2,), STRENGTH: (1,)}


def test_without_quality_hp_is_open():
    item = Item(ARMOR, 18, None, False, {HP: 1620, BAS: 1, STRENGTH: 81})
    assert levels(item)[HP] == (1, 2, 3, 4, 5)


def test_quality_that_does_not_fit_is_flagged():
    # Strength 5 + BAS 5 already needs at least 11/15 = 73%
    rolls = compute_rolls(Item(ARMOR, 18, 40, False, {HP: 1620, BAS: 2, STRENGTH: 81}), DATA)
    assert not rolls[STRENGTH].consistent
    assert rolls[HP].text == "?"


def test_normal_ring_negative_and_quality():
    # Tier XV normal ring: strength -90 is the -2 roll, vitality 57 is Low: (2 + 5) / 14 = 50%
    item = Item(RING, 15, 50, False, {STRENGTH: -90, VITALITY: 57})
    assert levels(item) == {STRENGTH: (2,), VITALITY: (5,)}
    assert all(roll.consistent for roll in compute_rolls(item, DATA).values())


@pytest.mark.parametrize(
    "roll, text",
    [
        (Roll((4,), 5, {}), "4/5"),
        (Roll((3, 4, 5), 5, {}), "3-5/5"),
        (Roll((1, 3), 5, {}), "1,3/5"),
        (Roll((2,), 5, {}, consistent=False), "2/5?"),
    ],
)
def test_text(roll, text):
    assert roll.text == text


GEAR = DATA["gear"]


@pytest.mark.parametrize(
    "stat, kind, tier, excellent, expected",
    [
        (STRENGTH, ARMOR, 4, False, (3, 4)),  # Spiderfang: +3 is High, +4 Highest
        (STRENGTH, ARMOR, 18, False, (49, 81)),
        (STRENGTH, ARMOR, 18, True, (55, 91)),
        (STRENGTH, ARMOR, 19, True, (60, 100)),  # not Tier 20 normal (90 / 150)
        (STRENGTH, ARMOR, 22, False, (109, 182)),  # Null, as seen in game
        (STRENGTH, ARMOR, 22, True, (120, 199)),
        (STRENGTH, ARMOR, 23, False, (122.6, 204.8)),  # one tier past the table: scaled
        (VITALITY, WEAPON, 16, False, (128, 320)),  # Rhodonite Fire Staff Vitality -320 is Lowest
        (VITALITY, WEAPON, 22, True, (397, 992)),
        (BAS, WEAPON, 22, True, (7, 12)),  # the same at every tier
    ],
)
def test_gear_values(stat, kind, tier, excellent, expected):
    assert gear_values(stat, kind, tier, excellent, GEAR) == pytest.approx(expected, abs=0.1)


def test_unknown_values():
    assert gear_values(STRENGTH, ARMOR, 25, False, GEAR) is None  # too far past the table to scale
    assert gear_values(STRENGTH, ARMOR, 1, False, GEAR) == (None, 1)  # missing on the wiki
