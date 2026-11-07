"""Fixture backend: serves canned data from JSON files. No credentials needed.

Lookup order for a package: `<fixtures_dir>/<package>.json`, then `<fixtures_dir>/demo.json`.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from ..models import CrashIssue, RateMetrics, Release
from .base import BackendError


class FixtureBackend:
    def __init__(self, fixtures_dir: str | Path | None = None) -> None:
        self.dir = (
            Path(fixtures_dir)
            if fixtures_dir
            else Path(str(resources.files("release_health_mcp") / "fixtures"))
        )

    @cache  # noqa: B019 - backend instances are long-lived singletons
    def _load(self, package: str) -> dict[str, Any]:
        for candidate in (self.dir / f"{package}.json", self.dir / "demo.json"):
            if candidate.exists():
                data: dict[str, Any] = json.loads(candidate.read_text())
                return data
        raise BackendError(f"No fixture data for {package} in {self.dir}")

    def list_releases(self, package: str) -> list[Release]:
        return [Release.model_validate(r) for r in self._load(package)["releases"]]

    def rate_metrics(self, package: str, days: int) -> dict[int, RateMetrics]:
        rows = [RateMetrics.model_validate(m) for m in self._load(package)["metrics"]]
        return {m.version_code: m for m in rows}

    def error_issues(
        self, package: str, days: int, version_code: int | None, limit: int
    ) -> list[CrashIssue]:
        issues = [CrashIssue.model_validate(i) for i in self._load(package)["issues"]]
        if version_code is not None:
            issues = [
                i
                for i in issues
                if (i.first_version_code or 0) <= version_code <= (i.last_version_code or 1 << 62)
            ]
        issues.sort(key=lambda i: i.distinct_users, reverse=True)
        return issues[:limit]

    def sample_stack_trace(
        self, package: str, issue_name: str, version_code: int | None
    ) -> str | None:
        traces: dict[str, str] = self._load(package).get("stack_traces", {})
        return traces.get(issue_name)
