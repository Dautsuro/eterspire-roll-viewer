"""Decides when the tooltips must be read again, so labels disappear as soon as a tooltip closes or changes.

Reading the tooltips takes a few hundred milliseconds, but checking whether the pixels under them changed
takes a few: while labels are shown, every frame is compared with the one they were read from. After a
change, the new tooltip is first looked for where the old one was (fast), then in the whole frame.
"""

from __future__ import annotations

import time
from typing import Callable

import cv2
import numpy as np

from .reader import Panel, search_region

UNCHANGED, CHANGED, NOTHING_SHOWN = "unchanged", "changed", "nothing shown"
PIXEL_CHANGE = 40  # grey levels: text appearing or disappearing, not compression noise
CHANGED_PIXELS = 4  # this many changed pixels (in the half-size picture) means the tooltip changed


def panel_area(panel: Panel, shape) -> tuple[int, int, int, int]:
    """The tooltip's text from "Upgrade Level" to its last stat (not the item icon, which may sparkle)."""
    boxes = [line.box for line in panel.lines] + [panel.stats_box]
    unit = panel.unit
    left = max(0, int(min(b[0] for b in boxes) - unit))
    top = max(0, int(min(b[1] for b in boxes) - unit * 10))
    right = min(shape[1], int(max(b[2] for b in boxes) + unit))
    bottom = min(shape[0], int(max(b[3] for b in boxes) + unit * 0.5))
    return left, top, right, bottom


def _picture(frame: np.ndarray, area) -> np.ndarray:
    left, top, right, bottom = area
    gray = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (max(1, (right - left) // 2), max(1, (bottom - top) // 2)), interpolation=cv2.INTER_AREA)


class TooltipTracker:
    def __init__(self, read: Callable[..., list[Panel]], refresh_every: float = 1.5,
                 clock: Callable[[], float] = time.monotonic):
        self._read = read
        self.refresh_every = refresh_every
        self._clock = clock
        self.shown: list[Panel] = []
        self._pictures: list[tuple[tuple[int, int, int, int], np.ndarray]] = []
        self._last_read = float("-inf")
        self._shape: tuple[int, int] | None = None
        self._regions: list[tuple[int, int, int, int]] = []  # where the tooltips were before a change

    def look(self, frame: np.ndarray) -> str:
        """Compares the frame with the one the labels come from. On a change the labels are dropped at once."""
        if not self.shown:
            return NOTHING_SHOWN
        for area, before in self._pictures:
            now = _picture(frame, area) if frame.shape[:2] == self._shape else None
            if now is None or now.shape != before.shape or np.count_nonzero(
                    cv2.absdiff(now, before) > PIXEL_CHANGE) >= CHANGED_PIXELS:
                self._regions = [search_region(p, frame.shape) for p in self.shown] if now is not None else []
                self.shown, self._pictures = [], []
                return CHANGED
        return UNCHANGED

    def refresh_due(self) -> bool:
        """Unchanged tooltips are still read now and then, to notice a new one opening elsewhere."""
        return self._clock() - self._last_read >= self.refresh_every

    def read(self, frame: np.ndarray, refresh: bool = False) -> list[Panel]:
        """Reads the tooltips. A refresh of unchanged tooltips never hides labels because of a missed read."""
        panels, regions, self._regions = [], self._regions, []
        if regions and not refresh:
            panels = self._read(frame, regions)
        if panels:
            # Shown already; the whole frame is read on the next refresh, which comes right away.
            self._last_read = float("-inf")
        else:
            panels = self._read(frame)
            self._last_read = self._clock()
        if panels or not refresh:
            self.shown = panels
            self._shape = frame.shape[:2]
            self._pictures = [(area, _picture(frame, area)) for area in (panel_area(p, frame.shape) for p in panels)]
        return self.shown
