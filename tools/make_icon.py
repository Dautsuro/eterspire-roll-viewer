"""Generates the app icon (roll_viewer/assets/icon.png and icon.ico): bars rising from a bad roll to a perfect one.

Run once: python tools/make_icon.py  (needs Pillow)
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "roll_viewer" / "assets"
SIZE = 1024  # drawn big, then scaled down for smooth edges

PANEL = (135, 64, 46)  # the game's tooltip colour
GOLD = (232, 176, 48)
BARS = [(232, 72, 72), (240, 200, 70), (80, 220, 110)]  # the label colours: worst, average, best

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((24, 24, SIZE - 24, SIZE - 24), radius=200, fill=GOLD)
d.rounded_rectangle((84, 84, SIZE - 84, SIZE - 84), radius=150, fill=PANEL)
left, bottom, width, gap = 190, 840, 190, 52
for i, (color, height) in enumerate(zip(BARS, (250, 450, 650))):
    x = left + i * (width + gap)
    d.rounded_rectangle((x, bottom - height, x + width, bottom), radius=40, fill=color)

OUT.mkdir(parents=True, exist_ok=True)
small = img.resize((256, 256), Image.LANCZOS)
small.save(OUT / "icon.png")
small.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
