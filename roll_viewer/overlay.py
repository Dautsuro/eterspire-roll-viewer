"""A transparent, click-through window over the game that shows the roll labels."""

from __future__ import annotations

import sys
import tkinter as tk

from .overlay_draw import Label

KEY_COLOR = "#010203"  # painted pixels of this colour are fully transparent
BOX_COLOR = "#16110e"
FONT = "Segoe UI"


def _make_click_through(window: tk.Toplevel, hide_from_capture: bool) -> None:
    """No focus, no taskbar button, mouse clicks go to the game, and screenshots don't include it."""
    if sys.platform != "win32":
        return
    import ctypes

    GWL_EXSTYLE = -20
    WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x00080000, 0x00000020, 0x00000080
    WS_EX_TOPMOST, WS_EX_NOACTIVATE = 0x00000008, 0x08000000
    WDA_EXCLUDEFROMCAPTURE = 0x11
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE,
        style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
    )
    if hide_from_capture:  # keep the labels out of our own screenshots of the game (Windows 10 2004+)
        user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)


class Overlay:
    def __init__(self, root: tk.Tk, hide_from_capture: bool = True):
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg=KEY_COLOR)
        self.window.attributes("-transparentcolor", KEY_COLOR)
        self.canvas = tk.Canvas(self.window, bg=KEY_COLOR, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.window.update_idletasks()
        _make_click_through(self.window, hide_from_capture)
        self._visible = False
        self._geometry = ""
        self._drawn: tuple = ()

    def show(self, region: dict, labels: list[Label]) -> None:
        """Covers ``region`` (screen pixels) and draws ``labels`` (pixels relative to the region)."""
        geometry = f"{region['width']}x{region['height']}+{region['left']}+{region['top']}"
        if geometry != self._geometry:
            self.window.geometry(geometry)
            self._geometry = geometry
        key = tuple((lb.x, lb.y, lb.height, lb.text, lb.color) for lb in labels)
        if key != self._drawn:
            self._draw(labels)
            self._drawn = key
        if not self._visible:
            self.window.deiconify()
            self._visible = True
        self.window.lift()

    def hide(self) -> None:
        if self._visible:
            self.window.withdraw()
            self._visible = False

    def _draw(self, labels: list[Label]) -> None:
        self.canvas.delete("all")
        for label in labels:
            size = max(9, label.height)
            text = self.canvas.create_text(
                label.x, label.y, text=label.text, anchor="w", fill="#%02x%02x%02x" % label.color,
                font=(FONT, -size, "bold"),
            )
            x0, y0, x1, y1 = self.canvas.bbox(text)
            pad = max(2, size // 5)
            box = self.canvas.create_rectangle(x0 - pad, y0, x1 + pad, y1, fill=BOX_COLOR, outline="#4a3a2c")
            self.canvas.tag_lower(box, text)
