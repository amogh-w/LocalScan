from typing import Protocol, TypedDict

import numpy as np


class Line(TypedDict):
    text: str
    conf: float
    bbox: list[float]  # x0, y0, x1, y1 in image pixels


class Block(TypedDict):
    id: str
    bbox: list[float]
    lines: list[Line]
    flow: bool  # reflowable prose; otherwise lines are kept ("\n" in text)
    text: str


class OcrEngine(Protocol):
    name: str

    def ocr(self, img: np.ndarray) -> list[Line]: ...

    def health(self) -> tuple[bool, str]: ...
