"""Finds item tooltips in a screenshot of the game and reads their tier, quality and stats.

1. The whole frame is read once to find the "Stats:" line of every open tooltip.
2. Below it, each text row is cut out, cleaned up (text vs. panel background) and read again,
   enlarged: this is much more reliable on the game's small pixel font.
3. The rows above "Upgrade Level" give the name (Excellent or not) and the tier/quality line.

All sizes are relative to the height of the "Stats:" text, so any window size works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from .ocr import Line, Ocr, Word
from .rolls import (
    ARMOR, ATTACK_SPEED, BONUS_ATTACK_SPEED, DAMAGE, GEAR_STATS, HP, RING, RING_STATS, STRENGTH, VITALITY, WEAPON, Item,
)

FIRST_PASS_SCALE = 1.5
LINE_SCALE = 3.0
PANEL_LEFT, PANEL_RIGHT = 1.0, 34.0  # stats column, in "Stats:" heights from the "Stats:" word
STATS_DEPTH = 14.0  # how far below "Stats:" stat lines can be
HEADER_TOP, HEADER_BOTTOM = 9.0, 0.5  # name and tier lines, above "Upgrade Level"

_STATS_RE = re.compile(r"^\W*stats\W*$", re.I)
_UPGRADE_RE = re.compile(r"^\W*upgr\w*\s*le\w*", re.I)
_SLOT_RE = re.compile(r"slot\s*[:;.]?\s*(\w+)", re.I)
_END_RE = re.compile(r"weapon|ability|weight|locked|equipped|cannot", re.I)
_LABELS = [  # order matters: "Bonus Attack Speed" before "Attack Speed"
    (BONUS_ATTACK_SPEED, re.compile(r"bonus\s*attack\s*s\w*", re.I)),
    (ATTACK_SPEED, re.compile(r"attack\s*s[pq]e+d", re.I)),
    (DAMAGE, re.compile(r"dam[a-z]*", re.I)),
    (VITALITY, re.compile(r"vit[a-z1]*", re.I)),
    (STRENGTH, re.compile(r"str[ea]n[gq]\w*", re.I)),
    (HP, re.compile(r"\bH\s*P\b")),
]
_VALUE_RE = re.compile(r"^[^\w+\-−]*([+\-−]?)\s*(\d+)\s*%?(?:\s*\+\s*(\d+)\s*%?)?")
_LOOKALIKES = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1", "i": "1",
                             "S": "5", "s": "5", "Z": "2", "z": "2", "B": "8", "g": "9", "?": "7"})


@dataclass
class StatLine:
    stat: str
    value: int | None
    bonus: int | None
    text: str
    box: tuple[int, int, int, int]  # left, top, right, bottom of the text in frame pixels


@dataclass
class Panel:
    item: Item
    name: str
    lines: list[StatLine]
    unit: float  # height of the "Stats:" text in pixels
    stats_box: tuple[int, int, int, int]  # the "Stats:" title
    header: str = ""
    problems: list[str] = field(default_factory=list)

    def signature(self) -> tuple:
        item = self.item
        return (item.kind, item.tier, item.quality, item.excellent, tuple(sorted(item.stats.items())),
                tuple((ln.stat, ln.box[1] // 4) for ln in self.lines))


def normalize(text: str) -> str:
    """Undo the OCR's usual mistakes on this font: "%" read as "0/0", "o/o", "°/o"..."""
    text = re.sub(r"[0oO°][/7][0oO°]", "%", text)
    return text.replace("−", "-").replace("—", "-").replace("–", "-")


def _fix_digits(text: str) -> str:
    """Turn lookalike letters into digits inside numbers ("1O" -> "10", "+S%" -> "+5%"), not inside words."""

    def fix(match: re.Match) -> str:
        token = match.group(0)
        before = text[:match.start()].rstrip()[-1:]
        after = text[match.end():].lstrip()[:1]
        if any(c.isdigit() for c in token) or before in "+-" and before or after == "%":
            return token.translate(_LOOKALIKES)
        return token

    return re.sub(r"(?<![A-Za-z])[0-9OoDQIl|iSsZzBg?]+(?![A-Za-z])", fix, text)


def parse_stat_line(text: str) -> tuple[str, int | None, int | None] | None:
    """``"- Bonus Attack Speed: +7% + 5%"`` -> ``("bonus_attack_speed", 7, 5)``. None if it isn't a stat line."""
    text = normalize(text)
    for stat, pattern in _LABELS:
        match = pattern.search(text)
        if not match:
            continue
        rest = _fix_digits(text[match.end():])
        value = _VALUE_RE.match(rest)
        if not value:
            return stat, None, None
        sign, number, bonus = value.groups()
        number = int(number)
        return stat, -number if sign in "-−" and sign else number, int(bonus) if bonus else None
    return None


def parse_tier_quality(text: str) -> tuple[int | None, int | None]:
    text = normalize(text)
    tier = re.search(r"T\s*i\s*e\s*r\s*[^\d]{0,2}(\d{1,2})\b", _fix_digits(text))
    quality = re.search(r"Qu\w*\W*([\dOoIlS ]{1,6})%", text)
    q = None
    if quality:
        digits = re.sub(r"\s+", "", _fix_digits(quality.group(1)))
        if digits.isdigit() and 0 <= int(digits) <= 100:
            q = int(digits)
    return (int(tier.group(1)) if tier and 1 <= int(tier.group(1)) <= 40 else None), q


def text_strength(crop: np.ndarray) -> np.ndarray:
    """How strongly each pixel looks like text: brighter than, and different from, the panel colour."""
    pixels = crop.astype(np.float32)
    background = np.median(pixels.reshape(-1, 3), axis=0)
    distance = np.linalg.norm(pixels - background, axis=2)
    brighter = pixels.mean(axis=2) > background.mean()
    return np.where(brighter, distance, 0)


def _text_mask(strength: np.ndarray) -> np.ndarray:
    top = float(np.percentile(strength, 99.5))
    return strength > max(25.0, 0.35 * top)


def _rows(mask: np.ndarray, unit: float) -> list[tuple[int, int]]:
    """Vertical extents of the text rows in a mask."""
    filled = mask.sum(axis=1) >= 2
    rows, start, gap = [], None, 0
    max_gap = max(1, int(unit * 0.2))
    for y, on in enumerate(filled):
        if on:
            if start is None:
                start = y
            gap, end = 0, y
        elif start is not None:
            gap += 1
            if gap > max_gap:
                rows.append((start, end + 1))
                start = None
    if start is not None:
        rows.append((start, end + 1))
    return [(a, b) for a, b in rows if b - a >= unit * 0.5]


def _for_ocr(crop: np.ndarray) -> np.ndarray:
    """Black text on white, enlarged: what the OCR engine reads best."""
    strength = text_strength(crop)
    strength = cv2.resize(strength, None, fx=LINE_SCALE, fy=LINE_SCALE, interpolation=cv2.INTER_CUBIC)
    median, top = float(np.median(strength)), float(np.percentile(strength, 99.5))
    ink = strength > median + 0.35 * (top - median)
    image = np.where(ink, 0, 255).astype(np.uint8)
    pad = int(LINE_SCALE * 8)
    return cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)


def _read_rows(frame: np.ndarray, ocr: Ocr, left: int, top: int, right: int, bottom: int, unit: float):
    """Yield (text, box) for each text row inside the rectangle."""
    h, w = frame.shape[:2]
    left, right, top, bottom = max(0, left), min(w, right), max(0, top), min(h, bottom)
    if right - left < unit * 4 or bottom - top < unit:
        return
    region = frame[top:bottom, left:right]
    mask = _text_mask(text_strength(region))
    pad = max(2, int(unit * 0.4))
    for a, b in _rows(mask, unit):
        columns = np.flatnonzero(mask[a:b].any(axis=0))
        x0, x1 = int(columns[0]), int(columns[-1]) + 1
        crop = region[max(0, a - pad):b + pad, max(0, x0 - pad):x1 + pad]
        lines = ocr.read(_for_ocr(crop))
        text = " ".join(line.text for line in lines).strip()
        yield text, (left + x0, top + a, left + x1, top + b)


def _find_anchors(lines: list[Line]) -> list[tuple[Line, Line | None]]:
    """Each tooltip's "Stats:" line with the "Upgrade Level" line above it (if found)."""
    stats = [ln for ln in lines if _STATS_RE.match(ln.text)]
    upgrades = [ln for ln in lines if _UPGRADE_RE.match(ln.text) and not ln.text.lower().lstrip().startswith("m")]
    if not stats:  # fall back to the first stat line under an "Upgrade Level" line
        for up in upgrades:
            below = [ln for ln in lines if ln.y > up.y and abs(ln.x - up.x) < up.height * 3 and parse_stat_line(ln.text)]
            if below:
                first = min(below, key=lambda ln: ln.y)
                fake = Word("Stats:", first.x, first.y - first.height * 2.1, first.height * 4, first.height)
                stats.append(Line("Stats:", [fake]))
    anchors = []
    for st in stats:
        unit = st.height
        above = [up for up in upgrades if abs(up.x - st.x) < unit * 3 and 0 < st.y - up.y < unit * 16]
        anchors.append((st, max(above, key=lambda up: up.y) if above else None))
    return anchors


def _kind(slot: str | None, stats: dict, name: str) -> str:
    slot = (slot or "").lower()
    if slot.startswith("weap") or DAMAGE in stats:
        return WEAPON
    if slot.startswith("ring") or (re.search(r"\bring\b", name, re.I) and HP not in stats):
        return RING
    if slot or HP in stats:
        return ARMOR
    return RING if set(stats) <= set(RING_STATS) and stats else ARMOR


def search_region(panel: Panel, shape) -> tuple[int, int, int, int]:
    """Where to look for a tooltip opened in place of this one (its whole height, with room to shift)."""
    left, top, _, _ = panel.stats_box
    unit = panel.unit
    return (max(0, int(left - unit * 3)), max(0, int(top - unit * 26)),
            min(shape[1], int(left + unit * (PANEL_RIGHT + 3))), min(shape[0], int(top + unit * 18)))


def _first_pass(frame: np.ndarray, ocr: Ocr, regions) -> list[Line]:
    if regions is None:
        return ocr.read(frame, FIRST_PASS_SCALE)
    lines = []
    for left, top, right, bottom in regions:
        for line in ocr.read(frame[top:bottom, left:right], FIRST_PASS_SCALE):
            for word in line.words:
                word.x += left
                word.y += top
            lines.append(line)
    return lines


def read_panels(frame: np.ndarray, ocr: Ocr, regions: list[tuple[int, int, int, int]] | None = None) -> list[Panel]:
    """Reads every tooltip in the frame, or only those inside ``regions`` (much faster)."""
    first_pass = _first_pass(frame, ocr, regions)
    panels = []
    for stats_line, upgrade_line in _find_anchors(first_pass):
        unit = stats_line.height
        left = int(stats_line.x - unit * PANEL_LEFT)
        right = int(stats_line.x + unit * PANEL_RIGHT)

        lines: list[StatLine] = []
        top = int(stats_line.bottom + unit * 0.3)
        for text, box in _read_rows(frame, ocr, left, top, right, int(stats_line.y + unit * STATS_DEPTH), unit):
            parsed = parse_stat_line(text)
            if parsed is None:
                if _END_RE.search(text) or lines and len(text) > 3:
                    break
                continue
            lines.append(StatLine(parsed[0], parsed[1], parsed[2], text, box))
            if len(lines) >= 5:
                break
        if not lines:
            continue

        # Name, tier and quality: the rows above "Upgrade Level" (first-pass text helps when a row is missed).
        header_bottom = upgrade_line.y if upgrade_line else stats_line.y - unit * 8.5
        header_rows = [t for t, _ in _read_rows(frame, ocr, left, int(header_bottom - unit * HEADER_TOP), right,
                                                 int(header_bottom - unit * HEADER_BOTTOM), unit)]
        region_text = [ln.text for ln in first_pass
                       if left - unit * 2 <= ln.x <= right and header_bottom - unit * HEADER_TOP <= ln.y < stats_line.y]
        tier = quality = None
        for text in header_rows + region_text:
            t, q = parse_tier_quality(text)
            tier, quality = tier or t, quality if quality is not None else q
        name_rows = [t for t in header_rows if not re.search(r"Tier\s*\d", normalize(t)) and "Current" not in t]
        name = " ".join(name_rows).strip()
        excellent = any("xcellent" in t for t in header_rows + region_text)
        slot = next((m.group(1) for t in region_text if (m := _SLOT_RE.search(t))), None)

        stats = {ln.stat: ln.value for ln in lines if ln.stat != ATTACK_SPEED}
        kind = _kind(slot, stats, name + " " + " ".join(region_text))
        allowed = RING_STATS if kind == RING else GEAR_STATS[kind]
        problems = [f"unexpected {s}" for s in stats if s not in allowed]
        if tier is None:
            problems.append("tier not read")
        if quality is None:
            problems.append("quality not read")
        item = Item(kind, tier, quality, excellent, {s: v for s, v in stats.items() if s in allowed})
        stats_box = (int(stats_line.x), int(stats_line.y), int(stats_line.right), int(stats_line.bottom))
        panels.append(Panel(item, name, lines, unit, stats_box, " | ".join(header_rows), problems))
    return panels
