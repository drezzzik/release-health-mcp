"""Pure decision logic: expand / hold / halt. No I/O, fully unit-tested."""

from __future__ import annotations

from .models import CrashIssue, Decision, Recommendation, ReleaseHealth
from .thresholds import Thresholds


def relative_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous, 4)


def next_fraction(current: float, t: Thresholds) -> float:
    """Next rollout step above `current`, capped at current + max_step_pp."""
    cap = round(current + t.max_step_pp, 6)
    candidates = [s for s in t.rollout_steps if s > current + 1e-9]
    if not candidates:
        return 1.0
    return min(candidates[0], cap)


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def recommend(
    app: str,
    health: ReleaseHealth,
    new_issues: list[CrashIssue],
    t: Thresholds,
    current_fraction: float | None,
) -> Recommendation:
    halt: list[str] = []
    hold: list[str] = []
    ok: list[str] = []
    cur = health.current

    # 1. Absolute thresholds → halt.
    for label, value, limit in (
        (
            "User-perceived crash rate",
            cur.user_perceived_crash_rate,
            t.max_user_perceived_crash_rate,
        ),
        (
            "User-perceived ANR rate",
            cur.user_perceived_anr_rate,
            t.max_user_perceived_anr_rate,
        ),
    ):
        if value is None:
            hold.append(f"{label} has no data yet.")
        elif value > limit:
            halt.append(f"{label} {_pct(value)} exceeds the limit of {_pct(limit)}.")
        else:
            ok.append(f"{label} {_pct(value)} is within the limit of {_pct(limit)}.")

    # 2. Sample size.
    if cur.user_days < t.min_user_days:
        hold.append(
            f"Insufficient data: {cur.user_days} user-days, need at least {t.min_user_days}."
        )

    # 3. Regression vs previous version.
    if health.previous is None:
        hold.append("No previous version to compare against.")
    else:
        for label, change in (
            ("Crash rate", health.crash_rate_change),
            ("ANR rate", health.anr_rate_change),
        ):
            if change is not None and change > t.max_relative_increase:
                hold.append(
                    f"{label} is up {change * 100:+.0f}% vs version "
                    f"{health.previous.version_code} (max {t.max_relative_increase * 100:+.0f}%)."
                )

    # 4. Large new issues.
    for issue in new_issues:
        if issue.distinct_users > t.max_new_issue_users:
            hold.append(
                f"New {issue.type.lower()} issue '{issue.cause or issue.name}' affects "
                f"{issue.distinct_users} users (max {t.max_new_issue_users})."
            )

    decision: Decision
    suggested: float | None = None
    if halt:
        decision, reasons = "halt", halt + hold
    elif hold:
        decision, reasons, suggested = "hold", hold, current_fraction
    else:
        decision, reasons = "expand", ok or ["All checks passed."]
        if current_fraction is not None:
            if current_fraction >= 1.0:
                reasons.append("Rollout is already at 100%.")
                suggested = 1.0
            else:
                suggested = next_fraction(current_fraction, t)

    return Recommendation(
        app=app,
        version_code=cur.version_code,
        decision=decision,
        reasons=reasons,
        current_fraction=current_fraction,
        suggested_fraction=suggested,
        health=health,
        new_issues=new_issues,
    )
