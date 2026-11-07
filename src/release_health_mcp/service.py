"""Business logic behind the tools; independent of MCP so it is easy to test."""

from __future__ import annotations

from .backends import Backend, BackendError
from .config import Config
from .models import CrashIssue, Recommendation, Release, ReleaseHealth
from .recommend import recommend, relative_change
from .thresholds import ThresholdsFile


class ReleaseHealthService:
    def __init__(self, config: Config, backend: Backend, thresholds: ThresholdsFile) -> None:
        self.config = config
        self.backend = backend
        self.thresholds = thresholds

    def list_releases(self, app: str | None, track: str | None = "production") -> list[Release]:
        package = self.config.resolve_app(app)
        releases = self.backend.list_releases(package)
        if track and track != "all":
            releases = [r for r in releases if r.track == track]
        return releases

    def _default_version(self, package: str) -> int:
        """Highest versionCode in an in-progress/halted production release, else the highest one."""
        releases = [r for r in self.backend.list_releases(package) if r.track == "production"]
        staged = [r for r in releases if r.status in ("inProgress", "halted")]
        pool = staged or releases
        codes = [vc for r in pool for vc in r.version_codes]
        if not codes:
            raise BackendError(f"No production releases found for {package}.")
        return max(codes)

    def _current_fraction(self, package: str, version_code: int) -> float | None:
        for r in self.backend.list_releases(package):
            if r.track == "production" and version_code in r.version_codes:
                return r.effective_fraction
        return None

    def release_health(self, app: str | None, version_code: int | None) -> ReleaseHealth:
        package = self.config.resolve_app(app)
        vc = version_code or self._default_version(package)
        metrics = self.backend.rate_metrics(package, self.config.health_window_days)
        if vc not in metrics:
            raise BackendError(
                f"No vitals data for version {vc} of {package} in the last "
                f"{self.config.health_window_days} days. Versions with data: "
                f"{sorted(metrics, reverse=True)[:10]}"
            )
        current = metrics[vc]
        older = [v for v in metrics if v < vc and metrics[v].user_days > 0]
        previous = metrics[max(older)] if older else None
        return ReleaseHealth(
            app=package,
            current=current,
            previous=previous,
            crash_rate_change=relative_change(
                current.user_perceived_crash_rate,
                previous.user_perceived_crash_rate if previous else None,
            ),
            anr_rate_change=relative_change(
                current.user_perceived_anr_rate,
                previous.user_perceived_anr_rate if previous else None,
            ),
        )

    def top_crashes(
        self,
        app: str | None,
        version_code: int | None,
        limit: int = 5,
        with_stack: bool = True,
    ) -> list[CrashIssue]:
        package = self.config.resolve_app(app)
        vc = version_code or self._default_version(package)
        issues = self.backend.error_issues(package, self.config.health_window_days, vc, limit)
        if with_stack:
            for issue in issues:
                issue.sample_stack_trace = self.backend.sample_stack_trace(package, issue.name, vc)
        return issues

    def new_issues(
        self, app: str | None, version_code: int | None, limit: int = 20
    ) -> list[CrashIssue]:
        """Issues whose first occurrence (within the lookback window) is this version."""
        package = self.config.resolve_app(app)
        vc = version_code or self._default_version(package)
        issues = self.backend.error_issues(package, self.config.issues_window_days, None, 1000)
        return [i for i in issues if i.first_version_code == vc][:limit]

    def recommend_rollout(self, app: str | None, version_code: int | None) -> Recommendation:
        package = self.config.resolve_app(app)
        vc = version_code or self._default_version(package)
        health = self.release_health(package, vc)
        new = self.new_issues(package, vc)
        return recommend(
            app=package,
            health=health,
            new_issues=new,
            t=self.thresholds.for_app(package),
            current_fraction=self._current_fraction(package, vc),
        )
