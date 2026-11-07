"""Backend protocol: the data access the tools need, independent of the source."""

from __future__ import annotations

from typing import Protocol

from ..models import CrashIssue, RateMetrics, Release


class BackendError(Exception):
    """An anticipated data-source failure (permissions, unknown app, no data)."""


class Backend(Protocol):
    def list_releases(self, package: str) -> list[Release]:
        """Releases on all tracks (production first)."""
        ...

    def rate_metrics(self, package: str, days: int) -> dict[int, RateMetrics]:
        """Crash/ANR rates per versionCode, aggregated over the last `days` days of data."""
        ...

    def error_issues(
        self, package: str, days: int, version_code: int | None, limit: int
    ) -> list[CrashIssue]:
        """Crash and ANR issues ordered by distinct users, desc."""
        ...

    def sample_stack_trace(
        self, package: str, issue_name: str, version_code: int | None
    ) -> str | None:
        """One sample report text (stack trace) for an issue."""
        ...
