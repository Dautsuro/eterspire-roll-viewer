from pathlib import Path

import pytest

from roll_viewer.reader import parse_stat_line, parse_tier_quality
from roll_viewer.rolls import ATTACK_SPEED, BONUS_ATTACK_SPEED as BAS, DAMAGE, HP, STRENGTH, VITALITY

SCREENSHOTS = Path(__file__).parent / "screenshots"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("- Damage: 1805 + 370", (DAMAGE, 1805, 370)),
        ("- Attack Speed: 153", (ATTACK_SPEED, 153, None)),
        ("- Bonus Attack Speed: +7% + 50/0", (BAS, 7, 5)),
        ("- Bonus Attack Speed: -2% V", (BAS, -2, None)),
        ("- Vitality: +0 V", (VITALITY, 0, None)),
        ("� Vitality: +181 +37", (VITALITY, 181, 37)),
        ("- HP�. +1620 + 185", (HP, 1620, 185)),
        ("- Strength: +57 +2 A", (STRENGTH, 57, 2)),
        ("- Strength: +S7", (STRENGTH, 57, None)),
        ("- strength: +1O", (STRENGTH, 10, None)),
        ("Weapon Ability:", None),
        ("Weight: 1", None),
    ],
)
def test_parse_stat_line(text, expected):
    assert parse_stat_line(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Tier 18 - Quality: 86%", (18, 86)),
        ("Tier 16 - Quality: 730/0 V", (16, 73)),
        ("Tier 16 - Quality: 7 1 0/0", (16, 71)),
        ("Tier 18 - Quality:", (18, None)),
        ("Tier XVI Amber Ring (Excellent) +5", (None, None)),
    ],
)
def test_parse_tier_quality(text, expected):
    assert parse_tier_quality(text) == expected


EXPECTED = {
    "compare_weapon.png": {
        "Ominous Fire Staff": {DAMAGE: (5,), BAS: (4,), VITALITY: (4,)},
        "Rhodonite Thunder Staff": {DAMAGE: (4,), BAS: (4,), VITALITY: (3,)},
    },
    "live_compare_weapon.png": {
        "Ominous Fire Staff": {DAMAGE: (5,), BAS: (4,), VITALITY: (4,)},
        "Rhodonite Thunder Staff": {DAMAGE: (4,), BAS: (4,), VITALITY: (3,)},
    },
    "compare_armor.png": {
        "Rhodonite Thread Gown": {HP: (3,), BAS: (5,), STRENGTH: (4,)},
        "Topaz Thread Gown": {HP: (1,), BAS: (1,), STRENGTH: (5,)},
    },
    "equipped_boots.png": {"Ominous Thread Boots": {HP: (3,), BAS: (4,), STRENGTH: (5,)}},
    "equipped_cowl.png": {"Rhodonite Thread Cowl": {HP: (1,), BAS: (3,), STRENGTH: (5,)}},
    "equipped_ring.png": {"Amber": {STRENGTH: (6,), VITALITY: (4,)}},
}


@pytest.fixture(scope="module")
def ocr():
    pytest.importorskip("winrt.windows.media.ocr")
    from roll_viewer.ocr import Ocr

    engine = Ocr()
    yield engine
    engine.close()


@pytest.mark.parametrize("screenshot", sorted(EXPECTED))
def test_screenshots(ocr, screenshot):
    import cv2

    from roll_viewer.reader import read_panels
    from roll_viewer.rolls import compute_rolls, load_data

    panels = read_panels(cv2.imread(str(SCREENSHOTS / screenshot)), ocr)
    found = {}
    for panel in panels:
        name = next(n for n in EXPECTED[screenshot] if n in panel.name.replace("R Ing", "Ring"))
        found[name] = {s: r.levels for s, r in compute_rolls(panel.item, load_data()).items()}
    assert found == EXPECTED[screenshot]
