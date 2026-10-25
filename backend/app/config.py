"""Settings loaded from config.toml, with runtime overrides stored in data/settings.json."""
import json
import os
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.toml"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    def __init__(self) -> None:
        with CONFIG_PATH.open("rb") as f:
            self._base: dict[str, Any] = tomllib.load(f)
        # LOCALSCAN_DATA_DIR points a second instance at its own library (scripts/demo_library.py)
        self.data_dir = (ROOT / os.environ.get("LOCALSCAN_DATA_DIR", self._base["server"]["data_dir"])).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._overrides_path = self.data_dir / "settings.json"
        self._overrides: dict[str, Any] = {}
        if self._overrides_path.exists():
            self._overrides = json.loads(self._overrides_path.read_text("utf-8"))

    @property
    def values(self) -> dict[str, Any]:
        return _deep_merge(self._base, self._overrides)

    def section(self, *path: str) -> dict[str, Any]:
        node = self.values
        for p in path:
            node = node.get(p, {})
        return node

    def update(self, patch: dict[str, Any]) -> None:
        self._overrides = _deep_merge(self._overrides, patch)
        self._overrides_path.write_text(json.dumps(self._overrides, indent=2), "utf-8")


settings = Settings()
