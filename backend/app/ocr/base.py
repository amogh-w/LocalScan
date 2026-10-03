from typing import NotRequired, Protocol, TypedDict

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
    vertical: NotRequired[bool]  # one line of text running up the page: translated and drawn rotated
    keep: NotRequired[bool]  # stays exactly as in the photo: not translated, not erased, not retyped


class OcrEngine(Protocol):
    name: str

    def ocr(self, img: np.ndarray) -> list[Line]: ...

    def health(self) -> tuple[bool, str]: ...
