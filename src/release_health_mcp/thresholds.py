"""Rollout thresholds: defaults plus per-app overrides, loaded from thresholds.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class Thresholds(BaseModel):
    # Defaults match Google Play's "bad behavior" thresholds for Android vitals.
    max_user_perceived_crash_rate: float = 0.0109
    max_user_perceived_anr_rate: float = 0.0047
    max_relative_increase: float = Field(
        default=0.25,
        description="Max relative increase vs the previous version (0.25 = +25%).",
    )
    min_user_days: int = Field(
        default=500,
        description="Below this sample size, recommend hold (insufficient data).",
    )
    max_new_issue_users: int = Field(
        default=50,
        description="A single new issue affecting more users than this → hold.",
    )
    max_step_pp: float = Field(default=0.20, description="Max rollout increase per step (0-1).")
    rollout_steps: list[float] = Field(default_factory=lambda: [0.01, 0.05, 0.10, 0.20, 0.50, 1.0])

    @field_validator("rollout_steps")
    @classmethod
    def _sorted_steps(cls, v: list[float]) -> list[float]:
        if not v or any(not 0 < s <= 1 for s in v):
            raise ValueError("rollout_steps must be non-empty values in (0, 1]")
        return sorted(v)


class ThresholdsFile(BaseModel):
    defaults: Thresholds = Field(default_factory=Thresholds)
    apps: dict[str, dict[str, object]] = Field(default_factory=dict)

    def for_app(self, package: str) -> Thresholds:
        overrides = self.apps.get(package, {})
        return Thresholds.model_validate({**self.defaults.model_dump(), **overrides})


def load_thresholds(path: str | Path | None) -> ThresholdsFile:
    if path is None:
        return ThresholdsFile()
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Thresholds file not found: {p}")
    return ThresholdsFile.model_validate(yaml.safe_load(p.read_text()) or {})
