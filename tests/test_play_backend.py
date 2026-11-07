"""PlayBackend against recorded API responses (no network, no credentials)."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest
from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

from release_health_mcp.backends.base import BackendError
from release_health_mcp.backends.play import PlayBackend

from .conftest import recorded

PKG = "com.example.app"


def make(
    responses: list[tuple[dict[str, str], str]],
) -> tuple[PlayBackend, HttpMockSequence]:
    http = HttpMockSequence(responses)
    reporting = build("playdeveloperreporting", "v1beta1", http=http, static_discovery=True)
    publisher = build("androidpublisher", "v3", http=http, static_discovery=True)
    return PlayBackend(reporting=reporting, publisher=publisher, today=dt.date(2026, 11, 7)), http


OK = {"status": "200"}


def test_list_releases_reads_and_deletes_edit() -> None:
    backend, http = make(
        [(OK, json.dumps({"id": "edit-1"})), (OK, recorded("tracks_list")), (OK, "")]
    )
    releases = backend.list_releases(PKG)
    assert [(r.track, r.version_codes, r.status) for r in releases] == [
        ("production", [4130], "inProgress"),
        ("production", [4122], "completed"),
        ("internal", [4141], "completed"),
    ]
    assert releases[0].user_fraction == 0.1
    methods = [(m, u.split("?")[0]) for u, m, *_ in http.request_sequence]
    assert methods[-1][0] == "DELETE" and methods[-1][1].endswith("/edits/edit-1")
    assert not any(u.endswith(":commit") for _, u in methods)


def test_list_releases_deletes_edit_even_on_error() -> None:
    backend, http = make([(OK, json.dumps({"id": "e"})), ({"status": "500"}, "{}"), (OK, "")])
    with pytest.raises(BackendError):
        backend.list_releases(PKG)
    assert http.request_sequence[-1][1] == "DELETE"


def test_permission_error_is_readable() -> None:
    backend, _ = make([({"status": "403"}, json.dumps({"error": {"message": "denied"}}))])
    with pytest.raises(BackendError, match="Permission denied"):
        backend.list_releases(PKG)


def test_rate_metrics_user_weighted() -> None:
    backend, http = make(
        [
            (OK, recorded("crashrate_get")),
            (OK, recorded("crashrate_query")),
            (OK, recorded("anrrate_get")),
            (OK, recorded("anrrate_query")),
        ]
    )
    m = backend.rate_metrics(PKG, days=7)
    # (0.004*1000 + 0.007*3000) / 4000 = 0.00625
    assert m[4130].user_perceived_crash_rate == pytest.approx(0.00625)
    assert m[4130].user_perceived_anr_rate == pytest.approx(0.002)
    assert m[4130].user_days == 4000
    assert m[4122].user_perceived_anr_rate is None
    assert m[4130].end_date == "2026-11-06" and m[4130].start_date == "2026-10-30"

    body: dict[str, Any] = json.loads(http.request_sequence[1][2])
    assert body["dimensions"] == ["versionCode"]
    assert body["timelineSpec"]["endTime"]["timeZone"]["id"] == "America/Los_Angeles"


def test_error_issues_and_stack_trace() -> None:
    backend, http = make([(OK, recorded("issues_search")), (OK, recorded("reports_search"))])
    issues = backend.error_issues(PKG, days=7, version_code=4130, limit=5)
    assert [i.distinct_users for i in issues] == [214, 12]
    assert issues[1].first_version_code == 4130
    url = http.request_sequence[0][0]
    assert "versionCode+%3D+4130" in url or "versionCode%20%3D%204130" in url
    assert "orderBy=distinctUsers+desc" in url or "orderBy=distinctUsers%20desc" in url

    trace = backend.sample_stack_trace(PKG, issues[0].name, 4130)
    assert trace and trace.startswith("java.lang.IllegalStateException")
    assert "errorIssueId" in http.request_sequence[1][0]


def test_requires_key_without_injected_clients() -> None:
    with pytest.raises(BackendError, match="service-account key"):
        PlayBackend(None)
