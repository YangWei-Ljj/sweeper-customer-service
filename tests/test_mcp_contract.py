"""MCP 真实端到端契约测试（pytest-asyncio，子进程拉起 weather-mcp-server）。

不 mock 掉 MCP 协议本身：通过官方 stdio client 真实拉起 server.py 子进程，
完成 initialize 握手 -> list_tools 发现 -> call_tool 调用。

环境约定：本进程不设置 WEATHER_API_TOKEN，因此合法城市 get_weather 返回受控错误
MISSING_TOKEN（协议上算正常——证明握手与调用链路通）；非法城市返回 CITY_NOT_ALLOWED。
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.mcp import client as mcp_client  # noqa: E402

# 确保不携带 token（受控错误路径）
os.environ.pop("WEATHER_API_TOKEN", None)


@pytest.mark.asyncio
async def test_handshake_and_tool_discovery():
    tools = await mcp_client.discover_tools_async()
    names = {t["name"] for t in tools}
    assert "get_weather" in names
    assert "list_cities" in names
    gw = next(t for t in tools if t["name"] == "get_weather")
    schema = gw["inputSchema"]
    assert schema["type"] == "object"
    assert "location" in schema["properties"]
    assert "location" in schema["required"]


@pytest.mark.asyncio
async def test_list_cities_returns_whitelist():
    # list_cities 经 call_tool 调用（discover 只列 schema）
    from agent.mcp.client import _with_session

    async def _h(session):
        r = await session.call_tool("list_cities", arguments={})
        text = "".join(getattr(c, "text", "") for c in r.content)
        import json
        return json.loads(text)

    payload = await _with_session(_h)
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["count"] == 16
    assert "杭州" in data["cities"]


@pytest.mark.asyncio
async def test_get_weather_valid_city_without_token_is_missing_token():
    payload = await mcp_client.get_weather_async("杭州")
    # 无 token：协议正常，返回受控错误 MISSING_TOKEN
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "MISSING_TOKEN"


@pytest.mark.asyncio
async def test_get_weather_illegal_city_is_city_not_allowed():
    payload = await mcp_client.get_weather_async("火星")
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "CITY_NOT_ALLOWED"


def test_weather_tool_registered_and_gov_authorized():
    """MCP 天气工具纳入统一注册表且入参校验生效。"""
    from agent.registry import Outcome
    from agent.tool_registry import build_default_registry

    reg = build_default_registry()
    spec = reg.get("get_weather")
    assert spec is not None
    assert spec.permission.value == "read"
    assert reg.authorize("get_weather", {"location": "杭州"}).outcome == Outcome.ALLOW
    assert reg.authorize("get_weather", {"location": ""}).outcome == Outcome.DENY
