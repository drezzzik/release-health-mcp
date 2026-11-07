"""Server configuration: which apps exist, which backend to use, where keys live."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

BackendName = Literal["fixture", "play"]


class Config(BaseModel):
    backend: BackendName = "fixture"
    apps: dict[str, str] = Field(
        default_factory=dict,
        description="alias -> Play package name, e.g. shop: com.example.shop",
    )
    default_app: str | None = None
    read_key_file: str | None = Field(
        default=None,
        description="Service-account JSON with read-only Play Console access.",
    )
    thresholds_file: str | None = None
    fixtures_dir: str | None = None
    health_window_days: int = 7
    issues_window_days: int = 60

    def resolve_app(self, app: str | None) -> str:
        """Turn an alias or package name into a package name."""
        key = app or self.default_app
        if key is None:
            if len(self.apps) == 1:
                return next(iter(self.apps.values()))
            raise ValueError(
                f"No app given and no default_app configured. Known apps: {self.known_apps()}"
            )
        if key in self.apps:
            return self.apps[key]
        if key in self.apps.values() or not self.apps:
            return key
        raise ValueError(f"Unknown app {key!r}. Known apps: {self.known_apps()}")

    def known_apps(self) -> str:
        return ", ".join(f"{a} ({p})" for a, p in self.apps.items()) or "(none configured)"


def load_config(path: str | Path | None = None) -> Config:
    """Load config from RELEASE_HEALTH_CONFIG / ./config.yaml, then apply env overrides."""
    path = path or os.environ.get("RELEASE_HEALTH_CONFIG") or "config.yaml"
    p = Path(path).expanduser()
    data: dict[str, object] = {}
    if p.exists():
        data = yaml.safe_load(p.read_text()) or {}
        base = p.parent
        for key in ("read_key_file", "thresholds_file", "fixtures_dir"):
            val = data.get(key)
            if isinstance(val, str):
                data[key] = str(base / Path(val).expanduser())
    if backend := os.environ.get("RELEASE_HEALTH_BACKEND"):
        data["backend"] = backend
    if key_file := os.environ.get("RELEASE_HEALTH_READ_KEY"):
        data["read_key_file"] = key_file
    if thresholds := os.environ.get("RELEASE_HEALTH_THRESHOLDS"):
        data["thresholds_file"] = thresholds
    return Config.model_validate(data)
