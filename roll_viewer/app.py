"""Eterspire Roll Viewer: watches the game and labels every stat of an open item with its roll."""

from __future__ import annotations

import argparse
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cv2
import numpy as np

from . import tray
from .capture import ScreenGrabber, enable_dpi_awareness, find_window, is_foreground
from .ocr import Ocr
from .overlay import Overlay
from .overlay_draw import Label, layout
from .reader import Panel, read_panels
from .rolls import compute_rolls, load_data

APP_NAME = "Eterspire Roll Viewer"
LOG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "EterspireRollViewer"
FULL_READ_EVERY = 3.0  # seconds: read again even if the tooltips look unchanged
log = logging.getLogger("roll_viewer")


def _setup_logging(verbose: bool) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_DIR / "roll-viewer.log", maxBytes=500_000, backupCount=1, encoding="utf-8")
    handlers: list[logging.Handler] = [handler]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.WARNING, handlers=handlers, format="%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.DEBUG if verbose else logging.INFO)


def _already_running() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    ctypes.windll.kernel32.CreateMutexW(None, False, "EterspireRollViewerSingleInstance")
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def _panels_area(panels: list[Panel], shape) -> tuple[int, int, int, int] | None:
    """The part of the frame the open tooltips' text covers, to notice when it changes."""
    if not panels:
        return None
    boxes = [line.box for p in panels for line in p.lines] + [p.stats_box for p in panels]
    unit = max(p.unit for p in panels)
    left = max(0, int(min(b[0] for b in boxes) - unit * 2))
    top = max(0, int(min(b[1] for b in boxes) - unit * 10))
    right = min(shape[1], int(max(b[2] for b in boxes) + unit * 2))
    bottom = min(shape[0], int(max(b[3] for b in boxes) + unit))
    return left, top, right, bottom


def _thumbnail(frame: np.ndarray, area) -> np.ndarray:
    left, top, right, bottom = area
    gray = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (max(1, (right - left) // 4), max(1, (bottom - top) // 4)), interpolation=cv2.INTER_AREA)


class Watcher(threading.Thread):
    """Captures the game and reads its tooltips on a background thread; results go to ``results``."""

    def __init__(self, title: str, interval: float, ignore_focus: bool = False):
        super().__init__(daemon=True, name="watcher")
        self.title = title
        self.ignore_focus = ignore_focus
        self.interval = interval
        self.results: queue.Queue = queue.Queue(maxsize=2)
        self.paused = threading.Event()
        self.stopped = threading.Event()
        self.status = "starting"

    def _post(self, region: dict | None, labels: list[Label]) -> None:
        try:
            self.results.put_nowait((region, labels))
        except queue.Full:
            try:
                self.results.get_nowait()
            except queue.Empty:
                pass
            self.results.put_nowait((region, labels))

    def run(self) -> None:
        grabber, ocr, data = ScreenGrabber(), Ocr(), load_data()
        shown: list[Panel] = []
        pending = None  # signature of the last reading, which must repeat to replace what's shown
        empty_reads = 0
        last_full, area, thumb = 0.0, None, None
        logged: tuple = ()
        try:
            while not self.stopped.is_set():
                started = time.monotonic()
                try:
                    target, status = find_window(self.title)
                    if self.paused.is_set():
                        self.status = "paused"
                        self._post(None, [])
                    elif target is None or not (self.ignore_focus or is_foreground(target.hwnd)):
                        self.status = status if target is None else "waiting for the game to be in front"
                        self._post(None, [])
                    else:
                        frame = grabber.grab(target)
                        if area and thumb is not None and started - last_full < FULL_READ_EVERY:
                            now = _thumbnail(frame, area)
                            if now.shape == thumb.shape and float(np.mean(cv2.absdiff(now, thumb))) < 2.0:
                                self._post(target.region, self._labels(shown, data))
                                self._sleep(started)
                                continue
                        panels = read_panels(frame, ocr)
                        last_full = started
                        signature = tuple(p.signature() for p in panels)
                        if panels:
                            empty_reads = 0
                            if not shown or signature == pending:
                                shown = panels
                            pending = signature
                        else:
                            empty_reads += 1
                            pending = None
                            if empty_reads >= 2:
                                shown = []
                        area = _panels_area(shown, frame.shape)
                        thumb = _thumbnail(frame, area) if area else None
                        for panel in panels:
                            if panel.problems:
                                log.debug("%s: %s %s", panel.name, panel.problems, panel.item)
                        self.status = f"{len(shown)} item(s) on screen" if shown else "watching"
                        shown_signature = tuple(p.signature() for p in shown)
                        if shown_signature != logged:
                            logged = shown_signature
                            log.debug("%s: %s", self.status, "; ".join(f"{p.name} {p.item}" for p in shown))
                        self._post(target.region, self._labels(shown, data))
                except Exception:  # keep watching whatever happens; the log says what went wrong
                    log.exception("reading the screen failed")
                    self.status = "error, see the log"
                    time.sleep(1)
                self._sleep(started)
        finally:
            grabber.close()
            ocr.close()

    @staticmethod
    def _labels(panels: list[Panel], data: dict) -> list[Label]:
        return layout([(p, compute_rolls(p.item, data)) for p in panels])

    def _sleep(self, started: float) -> None:
        self.stopped.wait(max(0.05, self.interval - (time.monotonic() - started)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", default="Eterspire", help="game window title (default: Eterspire)")
    parser.add_argument("--interval", type=float, default=0.4, help="seconds between screen reads (default: 0.4)")
    parser.add_argument("--verbose", action="store_true", help="log every reading problem")
    parser.add_argument("--debug", action="store_true",
                        help="also show the labels when the game isn't in front, and in screenshots")
    args = parser.parse_args()

    _setup_logging(args.verbose or args.debug)
    if _already_running():
        log.info("already running")
        return
    enable_dpi_awareness()

    root = tk.Tk()
    root.withdraw()
    overlay = Overlay(root, hide_from_capture=not args.debug)
    watcher = Watcher(args.title, args.interval, ignore_focus=args.debug)

    def quit_app() -> None:
        watcher.stopped.set()
        root.quit()

    def toggle() -> None:
        if watcher.paused.is_set():
            watcher.paused.clear()
        else:
            watcher.paused.set()

    icon = None
    if tray.available():
        icon = tray.TrayIcon(on_toggle=toggle, on_quit=lambda: root.after(0, quit_app),
                             is_paused=watcher.paused.is_set)

    last_status = ""

    def poll() -> None:
        nonlocal last_status
        try:
            region, labels = watcher.results.get_nowait()
            if region and labels:
                overlay.show(region, labels)
            else:
                overlay.hide()
        except queue.Empty:
            pass
        if icon is not None and watcher.status != last_status:
            last_status = watcher.status
            icon.set_tooltip(f"{APP_NAME}: {last_status}")
        root.after(50, poll)

    watcher.start()
    root.after(50, poll)
    log.info("started, watching the window called %r", args.title)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stopped.set()
        if icon is not None:
            icon.stop()
        watcher.join(timeout=3)


if __name__ == "__main__":
    main()
