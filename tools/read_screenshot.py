"""Reads item tooltips from screenshots and prints what the overlay would show.

    python tools/read_screenshot.py tests/screenshots/*.png [--save annotated/]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roll_viewer.ocr import Ocr  # noqa: E402
from roll_viewer.overlay_draw import draw_labels  # noqa: E402
from roll_viewer.reader import read_panels  # noqa: E402
from roll_viewer.rolls import compute_rolls, load_data  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--save", type=Path, help="folder for copies of the screenshots with the labels drawn on")
    args = parser.parse_args()
    ocr, data = Ocr(), load_data()
    for path in args.images:
        frame = cv2.imread(str(path))
        start = time.perf_counter()
        panels = read_panels(frame, ocr)
        ms = (time.perf_counter() - start) * 1000
        print(f"== {path.name}: {len(panels)} item(s) in {ms:.0f} ms")
        labelled = []
        for panel in panels:
            item = panel.item
            print(f"  {panel.name!r} [{panel.header}]")
            print(f"  {item.kind} tier={item.tier} quality={item.quality} excellent={item.excellent} {item.stats}"
                  + (f"  problems: {panel.problems}" if panel.problems else ""))
            rolls = compute_rolls(item, data)
            for line in panel.lines:
                roll = rolls.get(line.stat)
                print(f"    {line.text!r:50} -> {roll.text + ' ' + roll.name if roll else ''}")
            labelled.append((panel, rolls))
        if args.save:
            args.save.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(args.save / path.name), draw_labels(frame.copy(), labelled))


if __name__ == "__main__":
    main()
