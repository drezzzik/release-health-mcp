"""Record real Play API responses as test fixtures (read-only calls only).

Usage:
    uv run python scripts/record_responses.py --package com.example.app \
        --key ~/.config/release-health/play-read-only.json --out tests/recorded/ada [--scrub]

--scrub replaces the package name with com.example.app and drops issue URIs, so the files can be
committed to a public repo. Review the output before committing: stack traces may contain
class names you consider sensitive.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

from release_health_mcp.backends.play import ANR_METRICS, CRASH_METRICS, SCOPES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--out", default="tests/recorded/live")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--scrub", action="store_true")
    args = ap.parse_args()

    creds = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
        str(Path(args.key).expanduser()), scopes=SCOPES
    )
    reporting = build("playdeveloperreporting", "v1beta1", credentials=creds, cache_discovery=False)
    publisher = build("androidpublisher", "v3", credentials=creds, cache_discovery=False)
    pkg: str = args.package
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def save(name: str, data: dict[str, Any]) -> None:
        text = json.dumps(data, indent=2)
        if args.scrub:
            text = text.replace(pkg, "com.example.app")
            data = json.loads(text)
            for issue in data.get("errorIssues", []):
                issue.pop("issueUri", None)
            text = json.dumps(data, indent=2)
        (out / f"{name}.json").write_text(text + "\n")
        print(f"wrote {out / name}.json")

    edits = publisher.edits()
    edit_id = edits.insert(packageName=pkg, body={}).execute()["id"]
    try:
        save("tracks_list", edits.tracks().list(packageName=pkg, editId=edit_id).execute())
    finally:
        with contextlib.suppress(Exception):
            edits.delete(packageName=pkg, editId=edit_id).execute()

    vitals = reporting.vitals()
    for label, resource, metric_set, metrics in (
        ("crashrate", vitals.crashrate(), "crashRateMetricSet", CRASH_METRICS),
        ("anrrate", vitals.anrrate(), "anrRateMetricSet", ANR_METRICS),
    ):
        name = f"apps/{pkg}/{metric_set}"
        info = resource.get(name=name).execute()
        save(f"{label}_get", info)
        daily = next(
            f["latestEndTime"]
            for f in info["freshnessInfo"]["freshnesses"]
            if f["aggregationPeriod"] == "DAILY"
        )
        end = dt.date(daily["year"], daily["month"], daily["day"])
        start = end - dt.timedelta(days=args.days)
        tz = daily.get("timeZone")
        body = {
            "timelineSpec": {
                "aggregationPeriod": "DAILY",
                "startTime": {"year": start.year, "month": start.month, "day": start.day}
                | ({"timeZone": tz} if tz else {}),
                "endTime": {k: daily[k] for k in ("year", "month", "day")}
                | ({"timeZone": tz} if tz else {}),
            },
            "dimensions": ["versionCode"],
            "metrics": metrics,
            "pageSize": 10000,
        }
        save(f"{label}_query", resource.query(name=name, body=body).execute())

    today = dt.datetime.now(dt.UTC).date()
    start = today - dt.timedelta(days=args.days)
    interval = {
        "interval_startTime_year": start.year,
        "interval_startTime_month": start.month,
        "interval_startTime_day": start.day,
        "interval_startTime_timeZone_id": "UTC",
        "interval_endTime_year": today.year,
        "interval_endTime_month": today.month,
        "interval_endTime_day": today.day,
        "interval_endTime_timeZone_id": "UTC",
    }
    errors = vitals.errors()
    issues = (
        errors.issues()
        .search(
            parent=f"apps/{pkg}",
            filter="errorIssueType = CRASH OR errorIssueType = ANR",
            orderBy="distinctUsers desc",
            pageSize=10,
            **interval,
        )
        .execute()
    )
    save("issues_search", issues)
    if issues.get("errorIssues"):
        issue_id = issues["errorIssues"][0]["name"].rsplit("/", 1)[-1]
        save(
            "reports_search",
            errors.reports()
            .search(
                parent=f"apps/{pkg}", filter=f"errorIssueId = {issue_id}", pageSize=1, **interval
            )
            .execute(),
        )


if __name__ == "__main__":
    main()
