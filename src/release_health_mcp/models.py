"""Data models returned by the tools (serialized as structured MCP output)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ReleaseStatus = Literal["draft", "inProgress", "halted", "completed", "statusUnspecified"]
Decision = Literal["expand", "hold", "halt"]


class Release(BaseModel):
    track: str
    name: str | None = None
    version_codes: list[int]
    status: ReleaseStatus
    user_fraction: float | None = Field(
        default=None,
        description="Staged rollout fraction (0-1). None means 100% / not staged.",
    )

    @property
    def effective_fraction(self) -> float:
        if self.status == "completed":
            return 1.0
        return self.user_fraction if self.user_fraction is not None else 0.0


class RateMetrics(BaseModel):
    """Crash and ANR rates for a single versionCode, aggregated over a date window."""

    version_code: int
    user_perceived_crash_rate: float | None = None
    crash_rate: float | None = None
    user_perceived_anr_rate: float | None = None
    anr_rate: float | None = None
    user_days: int = Field(
        default=0,
        description="Sum of daily distinct users across the window (sample size).",
    )
    start_date: str | None = None
    end_date: str | None = None


class ReleaseHealth(BaseModel):
    app: str
    current: RateMetrics
    previous: RateMetrics | None = None
    crash_rate_change: float | None = Field(
        default=None,
        description="Relative change of user-perceived crash rate vs previous.",
    )
    anr_rate_change: float | None = Field(
        default=None,
        description="Relative change of user-perceived ANR rate vs previous.",
    )


class CrashIssue(BaseModel):
    name: str
    type: str = Field(description="CRASH, ANR or NON_FATAL")
    cause: str | None = None
    location: str | None = None
    distinct_users: int = 0
    error_report_count: int = 0
    first_version_code: int | None = None
    last_version_code: int | None = None
    issue_uri: str | None = None
    sample_stack_trace: str | None = None


class Recommendation(BaseModel):
    app: str
    version_code: int
    decision: Decision
    reasons: list[str]
    current_fraction: float | None = None
    suggested_fraction: float | None = None
    health: ReleaseHealth
    new_issues: list[CrashIssue] = Field(default_factory=list)
