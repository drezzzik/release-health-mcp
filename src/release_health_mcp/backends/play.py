"""Google Play backend: Play Developer Reporting API (vitals) + Android Publisher API (tracks).

Read-only. `list_releases` opens an edit to read tracks and always deletes it, never commits.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from collections import defaultdict
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..models import CrashIssue, RateMetrics, Release
from .base import BackendError

SCOPES = [
    "https://www.googleapis.com/auth/playdeveloperreporting",
    "https://www.googleapis.com/auth/androidpublisher",
]

CRASH_METRICS = ["userPerceivedCrashRate", "crashRate", "distinctUsers"]
ANR_METRICS = ["userPerceivedAnrRate", "anrRate", "distinctUsers"]


def _http_error(e: HttpError, package: str) -> BackendError:
    status = getattr(e.resp, "status", None)
    if status in (401, 403):
        return BackendError(
            f"Permission denied for {package} ({status}). Check that the service account is "
            "invited in Play Console for this app with 'View app information (read-only)' and "
            "'View app quality information (read-only)'. New permissions can take hours to apply."
        )
    if status == 404:
        return BackendError(f"Not found for {package}: is the package name correct?")
    return BackendError(f"Google API error for {package} ({status}): {e.reason}")


def _date(d: dict[str, Any]) -> dt.date:
    return dt.date(int(d["year"]), int(d["month"]), int(d["day"]))


def _datetime_dict(d: dt.date, tz: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"year": d.year, "month": d.month, "day": d.day}
    if tz:
        out["timeZone"] = {"id": tz}
    return out


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class PlayBackend:
    def __init__(
        self,
        key_file: str | None = None,
        *,
        reporting: Any = None,
        publisher: Any = None,
        today: dt.date | None = None,
    ) -> None:
        """Pass `key_file` for real use; tests inject prebuilt `reporting`/`publisher` clients."""
        if reporting is None or publisher is None:
            if not key_file:
                raise BackendError(
                    "Play backend needs a service-account key: set read_key_file in config.yaml "
                    "or RELEASE_HEALTH_READ_KEY."
                )
            from_file = service_account.Credentials.from_service_account_file
            creds = from_file(key_file, scopes=SCOPES)  # type: ignore[no-untyped-call]
            reporting = reporting or build(
                "playdeveloperreporting",
                "v1beta1",
                credentials=creds,
                cache_discovery=False,
            )
            publisher = publisher or build(
                "androidpublisher", "v3", credentials=creds, cache_discovery=False
            )
        self.reporting = reporting
        self.publisher = publisher
        self._today = today

    # ---- tracks ---------------------------------------------------------------------------

    def list_releases(self, package: str) -> list[Release]:
        edits = self.publisher.edits()
        try:
            edit_id = edits.insert(packageName=package, body={}).execute()["id"]
        except HttpError as e:
            raise _http_error(e, package) from e
        try:
            tracks = edits.tracks().list(packageName=package, editId=edit_id).execute()
        except HttpError as e:
            raise _http_error(e, package) from e
        finally:
            # Edits expire on their own; never fail a read because cleanup failed.
            with contextlib.suppress(HttpError):
                edits.delete(packageName=package, editId=edit_id).execute()

        out: list[Release] = []
        for track in tracks.get("tracks", []):
            for r in track.get("releases", []):
                out.append(
                    Release(
                        track=track["track"],
                        name=r.get("name"),
                        version_codes=[int(v) for v in r.get("versionCodes", [])],
                        status=r.get("status", "statusUnspecified"),
                        user_fraction=r.get("userFraction"),
                    )
                )
        out.sort(key=lambda r: (r.track != "production", r.track))
        return out

    # ---- vitals ---------------------------------------------------------------------------

    def _latest_daily(self, resource: Any, name: str) -> tuple[dt.date, str | None]:
        info = resource.get(name=name).execute().get("freshnessInfo", {})
        for f in info.get("freshnesses", []):
            if f.get("aggregationPeriod") == "DAILY":
                end = f["latestEndTime"]
                return _date(end), end.get("timeZone", {}).get("id")
        raise BackendError(f"No daily data available yet for {name}.")

    def _query_rates(
        self, resource: Any, name: str, metrics: list[str], days: int
    ) -> dict[int, dict[str, Any]]:
        """Daily rows per versionCode → user-weighted averages over the window."""
        end, tz = self._latest_daily(resource, name)
        start = end - dt.timedelta(days=days)
        body: dict[str, Any] = {
            "timelineSpec": {
                "aggregationPeriod": "DAILY",
                "startTime": _datetime_dict(start, tz),
                "endTime": _datetime_dict(end, tz),
            },
            "dimensions": ["versionCode"],
            "metrics": metrics,
            "pageSize": 10000,
        }
        sums: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        while True:
            resp = resource.query(name=name, body=body).execute()
            for row in resp.get("rows", []):
                vc = None
                for dim in row.get("dimensions", []):
                    if dim.get("dimension") == "versionCode":
                        vc = _int(dim.get("int64Value", dim.get("stringValue")))
                if vc is None:
                    continue
                values = {
                    m["metric"]: float(m["decimalValue"]["value"])
                    for m in row.get("metrics", [])
                    if "decimalValue" in m
                }
                users = values.get("distinctUsers", 0.0)
                acc = sums[vc]
                acc["users"] += users
                for metric, v in values.items():
                    if metric != "distinctUsers":
                        acc[metric] += v * users
                        acc[f"{metric}__w"] += users
            token = resp.get("nextPageToken")
            if not token:
                break
            body["pageToken"] = token

        out: dict[int, dict[str, Any]] = {}
        for vc, acc in sums.items():
            row_out: dict[str, Any] = {
                "users": int(acc["users"]),
                "start": start,
                "end": end,
            }
            for metric in metrics:
                w = acc.get(f"{metric}__w", 0.0)
                if metric != "distinctUsers" and w > 0:
                    row_out[metric] = acc[metric] / w
            out[vc] = row_out
        return out

    def rate_metrics(self, package: str, days: int) -> dict[int, RateMetrics]:
        vitals = self.reporting.vitals()
        try:
            crash = self._query_rates(
                vitals.crashrate(),
                f"apps/{package}/crashRateMetricSet",
                CRASH_METRICS,
                days,
            )
            anr = self._query_rates(
                vitals.anrrate(), f"apps/{package}/anrRateMetricSet", ANR_METRICS, days
            )
        except HttpError as e:
            raise _http_error(e, package) from e

        out: dict[int, RateMetrics] = {}
        for vc in set(crash) | set(anr):
            c, a = crash.get(vc, {}), anr.get(vc, {})
            ref = c or a
            out[vc] = RateMetrics(
                version_code=vc,
                user_perceived_crash_rate=c.get("userPerceivedCrashRate"),
                crash_rate=c.get("crashRate"),
                user_perceived_anr_rate=a.get("userPerceivedAnrRate"),
                anr_rate=a.get("anrRate"),
                user_days=int(c.get("users") or a.get("users") or 0),
                start_date=ref["start"].isoformat(),
                end_date=ref["end"].isoformat(),
            )
        return out

    # ---- errors ---------------------------------------------------------------------------

    def _interval(self, days: int) -> dict[str, Any]:
        end = self._today or dt.datetime.now(dt.UTC).date()
        start = end - dt.timedelta(days=days)
        params: dict[str, Any] = {}
        for prefix, d in (("interval_startTime", start), ("interval_endTime", end)):
            params[f"{prefix}_year"] = d.year
            params[f"{prefix}_month"] = d.month
            params[f"{prefix}_day"] = d.day
            params[f"{prefix}_timeZone_id"] = "UTC"
        return params

    def error_issues(
        self, package: str, days: int, version_code: int | None, limit: int
    ) -> list[CrashIssue]:
        flt = "(errorIssueType = CRASH OR errorIssueType = ANR)"
        if version_code is not None:
            flt += f" AND versionCode = {version_code}"
        issues_api = self.reporting.vitals().errors().issues()
        out: list[CrashIssue] = []
        token: str | None = None
        try:
            while len(out) < limit:
                kwargs: dict[str, Any] = {
                    "parent": f"apps/{package}",
                    "filter": flt,
                    "orderBy": "distinctUsers desc",
                    "pageSize": min(limit, 1000),
                    **self._interval(days),
                }
                if token:
                    kwargs["pageToken"] = token
                resp = issues_api.search(**kwargs).execute()
                for i in resp.get("errorIssues", []):
                    out.append(
                        CrashIssue(
                            name=i["name"],
                            type=i.get("type", "UNKNOWN"),
                            cause=i.get("cause"),
                            location=i.get("location"),
                            distinct_users=_int(i.get("distinctUsers")) or 0,
                            error_report_count=_int(i.get("errorReportCount")) or 0,
                            first_version_code=_int(
                                i.get("firstAppVersion", {}).get("versionCode")
                            ),
                            last_version_code=_int(i.get("lastAppVersion", {}).get("versionCode")),
                            issue_uri=i.get("issueUri"),
                        )
                    )
                token = resp.get("nextPageToken")
                if not token:
                    break
        except HttpError as e:
            raise _http_error(e, package) from e
        return out[:limit]

    def sample_stack_trace(
        self, package: str, issue_name: str, version_code: int | None
    ) -> str | None:
        issue_id = issue_name.rsplit("/", 1)[-1]
        flt = f"errorIssueId = {issue_id}"
        if version_code is not None:
            flt += f" AND versionCode = {version_code}"
        try:
            resp = (
                self.reporting.vitals()
                .errors()
                .reports()
                .search(
                    parent=f"apps/{package}",
                    filter=flt,
                    pageSize=1,
                    **self._interval(30),
                )
                .execute()
            )
        except HttpError as e:
            raise _http_error(e, package) from e
        reports = resp.get("errorReports", [])
        text = reports[0].get("reportText") if reports else None
        return text if isinstance(text, str) else None
