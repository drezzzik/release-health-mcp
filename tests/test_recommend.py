from __future__ import annotations

import pytest

from release_health_mcp.models import CrashIssue, RateMetrics, ReleaseHealth
from release_health_mcp.recommend import next_fraction, recommend, relative_change
from release_health_mcp.thresholds import Thresholds

T = Thresholds()


def health(
    crash: float | None = 0.004,
    anr: float | None = 0.002,
    users: int = 10_000,
    prev_crash: float | None = 0.004,
    prev_anr: float | None = 0.002,
    has_prev: bool = True,
) -> ReleaseHealth:
    cur = RateMetrics(
        version_code=2,
        user_perceived_crash_rate=crash,
        user_perceived_anr_rate=anr,
        user_days=users,
    )
    prev = (
        RateMetrics(
            version_code=1,
            user_perceived_crash_rate=prev_crash,
            user_perceived_anr_rate=prev_anr,
            user_days=100_000,
        )
        if has_prev
        else None
    )
    return ReleaseHealth(
        app="pkg",
        current=cur,
        previous=prev,
        crash_rate_change=relative_change(crash, prev_crash) if has_prev else None,
        anr_rate_change=relative_change(anr, prev_anr) if has_prev else None,
    )


def issue(users: int) -> CrashIssue:
    return CrashIssue(name="i", type="CRASH", cause="NPE", distinct_users=users)


@pytest.mark.parametrize(
    ("h", "new", "fraction", "decision", "reason_fragment"),
    [
        (health(), [], 0.10, "expand", "within the limit"),
        (health(crash=0.02), [], 0.10, "halt", "crash rate 2.00% exceeds"),
        (health(anr=0.006), [], 0.10, "halt", "ANR rate 0.60% exceeds"),
        (health(users=100), [], 0.10, "hold", "Insufficient data"),
        (
            health(crash=0.006, prev_crash=0.004),
            [],
            0.10,
            "hold",
            "Crash rate is up +50%",
        ),
        (health(anr=0.003, prev_anr=0.002), [], 0.10, "hold", "ANR rate is up +50%"),
        (health(), [issue(51)], 0.10, "hold", "affects 51 users"),
        (health(), [issue(50)], 0.10, "expand", "within the limit"),
        (health(has_prev=False), [], 0.10, "hold", "No previous version"),
        (health(crash=None), [], 0.10, "hold", "no data yet"),
    ],
)
def test_decisions(
    h: ReleaseHealth,
    new: list[CrashIssue],
    fraction: float,
    decision: str,
    reason_fragment: str,
) -> None:
    rec = recommend("pkg", h, new, T, fraction)
    assert rec.decision == decision
    assert any(reason_fragment in r for r in rec.reasons), rec.reasons


def test_halt_wins_over_hold() -> None:
    rec = recommend("pkg", health(crash=0.02, users=10), [issue(500)], T, 0.05)
    assert rec.decision == "halt"
    assert rec.suggested_fraction is None


def test_hold_keeps_fraction() -> None:
    rec = recommend("pkg", health(users=1), [], T, 0.05)
    assert rec.suggested_fraction == 0.05


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (0.0, 0.01),
        (0.01, 0.05),
        (0.10, 0.20),
        (0.20, 0.40),
        (0.50, 0.70),
        (0.90, 1.0),
        (1.0, 1.0),
    ],
)
def test_next_fraction_respects_steps_and_cap(current: float, expected: float) -> None:
    assert next_fraction(current, T) == pytest.approx(expected)


def test_already_complete() -> None:
    rec = recommend("pkg", health(), [], T, 1.0)
    assert rec.decision == "expand"
    assert rec.suggested_fraction == 1.0
    assert any("already at 100%" in r for r in rec.reasons)


def test_relative_change_handles_missing() -> None:
    assert relative_change(None, 0.1) is None
    assert relative_change(0.1, 0) is None
    assert relative_change(0.15, 0.1) == 0.5


def test_new_issue_reason_uses_play_issue_fields() -> None:
    anr = CrashIssue(
        name="apps/p/errorIssues/1",
        type="APPLICATION_NOT_RESPONDING",
        cause="AppStartup.onCreate",
        location="Input dispatching timed out",
        distinct_users=99,
    )
    rec = recommend("pkg", health(), [anr], T, 0.1)
    assert rec.decision == "hold"
    assert "New ANR 'Input dispatching timed out in AppStartup.onCreate'" in rec.reasons[0]
