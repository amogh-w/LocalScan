from collections.abc import Callable
from typing import Protocol

from ..ocr.base import Block


class Translator(Protocol):
    name: str

    def translate_blocks(self, blocks: list[Block], src: str = "German", tgt: str = "English",
                         on_progress: Callable[[int, int], None] | None = None) -> list[str]:
        """Return one translation per block, in the same order."""
        ...

    def health(self) -> tuple[bool, str]: ...

    def cache_key(self) -> str:
        """Identifies engine + model so cached translations are reused only when they match."""
        ...
