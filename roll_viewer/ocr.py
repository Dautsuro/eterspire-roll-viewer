"""Text recognition with the OCR engine built into Windows 10/11 (no extra install needed)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import cv2
import numpy as np

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter


@dataclass
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float


@dataclass
class Line:
    text: str
    words: list[Word]

    @property
    def x(self) -> float:
        return min(w.x for w in self.words)

    @property
    def y(self) -> float:
        return min(w.y for w in self.words)

    @property
    def right(self) -> float:
        return max(w.x + w.w for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.y + w.h for w in self.words)

    @property
    def height(self) -> float:
        return float(np.median([w.h for w in self.words]))


class Ocr:
    """Runs the Windows OCR engine. Create and use it on a single thread."""

    def __init__(self, language: str = "en-US"):
        self._engine = OcrEngine.try_create_from_language(Language(language))
        if self._engine is None:
            self._engine = OcrEngine.try_create_from_user_profile_languages()
        if self._engine is None:
            raise RuntimeError("Windows OCR is not available: add an English language pack in Windows settings.")
        self._loop = asyncio.new_event_loop()

    def read(self, image: np.ndarray, scale: float = 1.0) -> list[Line]:
        """OCR a BGR or grayscale image. ``scale`` enlarges it first; coordinates come back unscaled."""
        if scale != 1.0:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        bgra = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA if image.ndim == 2 else cv2.COLOR_BGR2BGRA)
        height, width = bgra.shape[:2]
        writer = DataWriter()
        writer.write_bytes(bgra.tobytes())
        bitmap = SoftwareBitmap.create_copy_with_alpha_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, width, height, BitmapAlphaMode.PREMULTIPLIED
        )
        result = self._loop.run_until_complete(self._engine.recognize_async(bitmap))
        lines = []
        for line in result.lines:
            words = []
            for word in line.words:
                r = word.bounding_rect
                words.append(Word(word.text, r.x / scale, r.y / scale, r.width / scale, r.height / scale))
            if words:
                lines.append(Line(line.text, words))
        return lines

    def close(self) -> None:
        self._loop.close()
