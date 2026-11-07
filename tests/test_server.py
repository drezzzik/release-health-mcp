"""End-to-end through the MCP protocol, in-process, against the fixture backend."""

from __future__ import annotations

import pytest
from mcp import Client

from release_health_mcp.server import build_server
from release_health_mcp.service import ReleaseHealthService

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_tools_listed_and_read_only(service: ReleaseHealthService) -> None:
    async with Client(build_server(lambda: service)) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == {
        "list_releases",
        "get_release_health",
        "top_crashes",
        "new_issues",
        "recommend_rollout",
    }
    for t in tools.values():
        assert t.annotations and t.annotations.read_only_hint is True
        assert t.output_schema is not None


async def test_recommend_expand_for_healthy_app(service: ReleaseHealthService) -> None:
    async with Client(build_server(lambda: service)) as c:
        r = await c.call_tool("recommend_rollout", {"app": "demo"})
    assert not r.is_error
    assert r.structured_content
    assert r.structured_content["decision"] == "expand"
    assert r.structured_content["version_code"] == 4130
    assert r.structured_content["suggested_fraction"] == pytest.approx(0.2)


async def test_recommend_hold_for_regression(service: ReleaseHealthService) -> None:
    async with Client(build_server(lambda: service)) as c:
        r = await c.call_tool("recommend_rollout", {"app": "regressed"})
    assert r.structured_content and r.structured_content["decision"] == "hold"
    assert len(r.structured_content["reasons"]) == 2


async def test_new_issues_and_top_crashes(service: ReleaseHealthService) -> None:
    async with Client(build_server(lambda: service)) as c:
        new = await c.call_tool("new_issues", {})
        top = await c.call_tool("top_crashes", {"limit": 2})
    assert new.structured_content
    assert [i["first_version_code"] for i in new.structured_content["result"]] == [4130]
    assert top.structured_content
    first = top.structured_content["result"][0]
    assert first["distinct_users"] == 214 and first["sample_stack_trace"]


async def test_errors_are_clean(service: ReleaseHealthService) -> None:
    async with Client(build_server(lambda: service)) as c:
        bad_app = await c.call_tool("list_releases", {"app": "nope"})
        bad_version = await c.call_tool("get_release_health", {"version_code": 1})
    assert bad_app.is_error and "Known apps" in str(bad_app.content)
    assert bad_version.is_error and "No vitals data for version 1" in str(bad_version.content)
