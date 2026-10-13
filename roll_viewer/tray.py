"""Icon in the notification area: the app's only window of its own."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

ICON_PATH = Path(__file__).parent / "assets" / "icon.png"

try:
    import pystray
    from PIL import Image
except ImportError:  # the app still works without a tray icon
    pystray = None


def available() -> bool:
    return pystray is not None


class TrayIcon:
    """Runs on its own thread: the callbacks are called from that thread, not Tk's."""

    def __init__(self, on_toggle: Callable[[], None], on_quit: Callable[[], None], is_paused: Callable[[], bool]):
        menu = pystray.Menu(
            pystray.MenuItem(lambda _item: "Resume" if is_paused() else "Pause", lambda: on_toggle(), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: on_quit()),
        )
        self._icon = pystray.Icon("EterspireRollViewer", Image.open(ICON_PATH), "Eterspire Roll Viewer", menu)
        self._icon.run_detached()

    def set_tooltip(self, text: str) -> None:
        self._icon.title = text[:127]  # Windows tooltip limit
        self._icon.update_menu()

    def stop(self) -> None:
        self._icon.stop()
