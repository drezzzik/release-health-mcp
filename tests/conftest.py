from __future__ import annotations

import json
from pathlib import Path

import pytest

from release_health_mcp.backends import FixtureBackend
from release_health_mcp.config import Config
from release_health_mcp.service import ReleaseHealthService
from release_health_mcp.thresholds import ThresholdsFile

RECORDED = Path(__file__).parent / "recorded"


def recorded(name: str) -> str:
    return (RECORDED / f"{name}.json").read_text()


def recorded_json(name: str) -> dict[str, object]:
    data: dict[str, object] = json.loads(recorded(name))
    return data


@pytest.fixture
def config() -> Config:
    return Config(
        backend="fixture",
        apps={"demo": "com.example.app", "regressed": "com.example.regressed"},
        default_app="demo",
    )


@pytest.fixture
def service(config: Config) -> ReleaseHealthService:
    thresholds = ThresholdsFile.model_validate(
        {"apps": {"com.example.regressed": {"max_relative_increase": 0.15}}}
    )
    return ReleaseHealthService(config, FixtureBackend(), thresholds)
