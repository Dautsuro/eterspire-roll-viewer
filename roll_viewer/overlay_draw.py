"""Where each roll label goes and what it looks like (shared by the overlay and the debug tool)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .reader import Panel
from .rolls import ATTACK_SPEED, BONUS_ATTACK_SPEED, HP, Roll

SHORT_NAMES = {BONUS_ATTACK_SPEED: "Bonus AS", HP: "HP"}

# Worst roll .. best roll
_STOPS = [(0.0, (232, 72, 72)), (0.5, (240, 200, 70)), (1.0, (80, 220, 110))]
UNSURE_COLOR = (190, 190, 190)


@dataclass
class Label:
    x: int  # left edge, frame pixels
    y: int  # vertical centre, frame pixels
    height: int  # text height, frame pixels
    text: str
    color: tuple[int, int, int]  # RGB


def roll_color(roll: Roll) -> tuple[int, int, int]:
    if not roll.certain:
        return UNSURE_COLOR
    f = roll.fraction
    for (f0, c0), (f1, c1) in zip(_STOPS, _STOPS[1:]):
        if f <= f1:
            t = (f - f0) / (f1 - f0)
            return tuple(round(a + (b - a) * t) for a, b in zip(c0, c1))
    return _STOPS[-1][1]


def label_text(roll: Roll) -> str:
    return f"{roll.text} {roll.name}".strip()


def layout(labelled: list[tuple[Panel, dict[str, Roll]]]) -> list[Label]:
    labels = []
    for panel, rolls in labelled:
        for line in panel.lines:
            roll = rolls.get(line.stat)
            if roll is None:
                continue
            left, top, right, bottom = line.box
            labels.append(Label(int(right + panel.unit * 0.8), (top + bottom) // 2, int(round(panel.unit * 1.15)),
                                label_text(roll), roll_color(roll)))
        shown = {line.stat for line in panel.lines}
        hidden = [f"{SHORT_NAMES.get(stat, stat.title())} {label_text(roll)}"
                  for stat, roll in rolls.items() if stat not in shown and stat != ATTACK_SPEED]
        if hidden:  # stats without a line (a neutral roll) still count toward quality
            left, top, right, bottom = panel.stats_box
            labels.append(Label(int(right + panel.unit * 1.2), (top + bottom) // 2, int(round(panel.unit * 1.0)),
                                "hidden: " + ", ".join(hidden), UNSURE_COLOR))
        if panel.item.tier is None and panel.lines:
            # Make a missing tier visible rather than silently guessing.
            left, top, right, bottom = panel.lines[0].box
            labels.append(Label(left, int(top - panel.unit * 1.6), int(panel.unit), "tier?", UNSURE_COLOR))
    return labels


def draw_labels(frame: np.ndarray, labelled: list[tuple[Panel, dict[str, Roll]]]) -> np.ndarray:
    """Draws the labels on a BGR image, roughly as the overlay shows them."""
    for label in layout(labelled):
        scale = label.height / 22
        thickness = max(1, int(round(label.height / 10)))
        (w, h), base = cv2.getTextSize(label.text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
        x, y = label.x, label.y + h // 2
        pad = max(2, label.height // 4)
        cv2.rectangle(frame, (x - pad, y - h - pad), (x + w + pad, y + base + pad // 2), (20, 16, 14), -1)
        cv2.putText(frame, label.text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, label.color[::-1], thickness, cv2.LINE_AA)
    return frame
