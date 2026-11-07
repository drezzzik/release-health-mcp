"""MCP server exposing release-health tools (read-only)."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Annotated, ParamSpec, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from .backends import BackendError, make_backend
from .config import load_config
from .models import CrashIssue, Recommendation, Release, ReleaseHealth
from .service import ReleaseHealthService
from .thresholds import load_thresholds

INSTRUCTIONS = """\
Release health for Android apps on Google Play. Use these tools to decide whether a staged
rollout is healthy enough to expand. Typical flow: list_releases → recommend_rollout; drill into
get_release_health, top_crashes or new_issues to explain the decision. All tools are read-only:
this server never changes a rollout. `app` accepts a configured alias or a package name; omit
`version_code` to use the release currently rolling out on production. Rates are fractions
(0.0109 = 1.09% of users)."""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)

AppArg = Annotated[
    str | None,
    Field(description="App alias from config or Play package name. Optional if only one app."),
]
VersionArg = Annotated[
    int | None,
    Field(description="versionCode. Defaults to the release currently rolling out on production."),
]

P = ParamSpec("P")
R = TypeVar("R")


def _tool_errors[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Turn anticipated failures into clean tool errors (no stack traces for the model)."""

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except (BackendError, ValueError, FileNotFoundError) as e:
            raise ToolError(str(e)) from e

    return wrapper


def build_server(
    service_factory: Callable[[], ReleaseHealthService] | None = None,
) -> MCPServer:
    """Build the server. The service is created lazily, so a bad config surfaces as a tool error."""
    mcp = MCPServer("release-health", instructions=INSTRUCTIONS)
    holder: dict[str, ReleaseHealthService] = {}

    def default_factory() -> ReleaseHealthService:
        config = load_config()
        return ReleaseHealthService(
            config, make_backend(config), load_thresholds(config.thresholds_file)
        )

    def svc() -> ReleaseHealthService:
        if "s" not in holder:
            holder["s"] = (service_factory or default_factory)()
        return holder["s"]

    @mcp.tool(annotations=READ_ONLY)
    @_tool_errors
    def list_releases(
        app: AppArg = None,
        track: Annotated[
            str,
            Field(description="Track name (production, beta, internal, …) or 'all'."),
        ] = "production",
    ) -> list[Release]:
        """Current releases on a Play track with status and staged-rollout fraction."""
        return svc().list_releases(app, track)

    @mcp.tool(annotations=READ_ONLY)
    @_tool_errors
    def get_release_health(app: AppArg = None, version_code: VersionArg = None) -> ReleaseHealth:
        """Crash and ANR rates for a version, compared with the previous version that has data."""
        return svc().release_health(app, version_code)

    @mcp.tool(annotations=READ_ONLY)
    @_tool_errors
    def top_crashes(
        app: AppArg = None,
        version_code: VersionArg = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 5,
        include_stack_traces: bool = True,
    ) -> list[CrashIssue]:
        """Largest crash/ANR issues in a version by affected users, with a sample stack trace."""
        return svc().top_crashes(app, version_code, limit, include_stack_traces)

    @mcp.tool(annotations=READ_ONLY)
    @_tool_errors
    def new_issues(app: AppArg = None, version_code: VersionArg = None) -> list[CrashIssue]:
        """Crash/ANR issues first seen in this version (likely regressions)."""
        return svc().new_issues(app, version_code)

    @mcp.tool(annotations=READ_ONLY)
    @_tool_errors
    def recommend_rollout(app: AppArg = None, version_code: VersionArg = None) -> Recommendation:
        """Recommend expand, hold or halt for a staged rollout, with reasons, using thresholds.yaml.

        This is advice only; it does not change the rollout."""
        return svc().recommend_rollout(app, version_code)

    return mcp


mcp = build_server()


def main() -> None:
    mcp.run()
