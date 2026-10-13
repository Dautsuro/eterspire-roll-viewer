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

from . import tray
from .capture import ScreenGrabber, enable_dpi_awareness, find_window, is_foreground
from .ocr import Ocr
from .overlay import Overlay
from .overlay_draw import Label, layout
from .reader import Panel, read_panels
from .rolls import compute_rolls, load_data
from .tracker import CHANGED, UNCHANGED, TooltipTracker

APP_NAME = "Eterspire Roll Viewer"
LOG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "EterspireRollViewer"
LABELS_CHECK_EVERY = 0.1  # seconds between checks that the tooltips under the labels are unchanged
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
        tracker = TooltipTracker(lambda frame, regions=None: read_panels(frame, ocr, regions))
        logged: tuple = ()
        try:
            while not self.stopped.is_set():
                started = time.monotonic()
                wait = self.interval
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
                        state = tracker.look(frame)
                        if state == CHANGED:
                            self._post(target.region, [])  # take the old labels off before reading again
                            log.debug("tooltips changed")
                        if state != UNCHANGED:
                            tracker.read(frame)
                        elif tracker.refresh_due():
                            tracker.read(frame, refresh=True)
                        shown = tracker.shown
                        if shown:
                            wait = LABELS_CHECK_EVERY
                        self.status = f"{len(shown)} item(s) on screen" if shown else "watching"
                        signature = tuple(p.signature() for p in shown)
                        if signature != logged:
                            logged = signature
                            log.debug("%s: %s", self.status, "; ".join(f"{p.name} {p.item}" for p in shown))
                            for panel in shown:
                                if panel.problems:
                                    log.debug("%s: %s", panel.name, panel.problems)
                        self._post(target.region, self._labels(shown, data))
                except Exception:  # keep watching whatever happens; the log says what went wrong
                    log.exception("reading the screen failed")
                    self.status = "error, see the log"
                    wait = 1.0
                self.stopped.wait(max(0.02, wait - (time.monotonic() - started)))
        finally:
            grabber.close()
            ocr.close()

    @staticmethod
    def _labels(panels: list[Panel], data: dict) -> list[Label]:
        return layout([(p, compute_rolls(p.item, data)) for p in panels])



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
