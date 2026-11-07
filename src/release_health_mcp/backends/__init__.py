from __future__ import annotations

from ..config import Config
from .base import Backend, BackendError
from .fixture import FixtureBackend


def make_backend(config: Config) -> Backend:
    if config.backend == "play":
        from .play import PlayBackend  # lazy: google client import is slow

        return PlayBackend(config.read_key_file)
    return FixtureBackend(config.fixtures_dir)


__all__ = ["Backend", "BackendError", "FixtureBackend", "make_backend"]
