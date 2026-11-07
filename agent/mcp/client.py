"""MCP stdio Client（真实接入，天气工具经 MCP 调用）。

基于官方 mcp 1.27 SDK：
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters

对接一个可选的 weather MCP server（FastMCP，stdio）：
    - list_cities()        无入参，返回城市白名单
    - get_weather(location) 返回冻结字段或受控错误信封 {"status":"error","error":{"code","message"}}

stdio 卫生：子进程 stdout 仅 JSON-RPC；本进程日志走 stderr，不往子进程 stdout 写任何东西。

服务器路径：必须通过环境变量 WEATHER_MCP_SERVER 指定 server.py 的绝对路径；未配置时天气工具返回受控错误。
每次调用独立拉起/关闭子进程（简单、健壮、无 loop 生命周期问题）；server 启动约 1s。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from utils.logger_handler import logger

# MCP server 的 server.py 绝对路径，由 WEATHER_MCP_SERVER 指定
DEFAULT_SERVER_SCRIPT = ""


def server_script_path() -> str:
    script = os.getenv("WEATHER_MCP_SERVER", DEFAULT_SERVER_SCRIPT)
    if not script:
        raise FileNotFoundError(
            "未配置 WEATHER_MCP_SERVER：天气工具需要指向 weather MCP server 的 server.py；"
            "未配置时请忽略该工具或自行部署 server。"
        )
    return script


def _build_env() -> dict[str, str]:
    """透传天气相关环境变量；token 缺省由 server 返回受控错误 MISSING_TOKEN。"""
    env = dict(os.environ)
    for key in ("WEATHER_API_TOKEN", "WEATHER_TIMEOUT_SEC", "MCP_AUDIT_PATH",
                "WEATHER_API_BASE", "WEATHER_CACHE_TTL_SEC"):
        val = os.getenv(key)
        if val:
            env[key] = val
    return env


async def _with_session(handler):
    """拉起 stdio 子进程、握手、执行 handler(session)，自动清理。"""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    script = server_script_path()
    if not os.path.exists(script):
        raise FileNotFoundError(f"MCP server 脚本不存在：{script}")

    params = StdioServerParameters(
        command=sys.executable,
        args=[script],
        env=_build_env(),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await handler(session)


async def discover_tools_async() -> list[dict[str, Any]]:
    """握手并列出 server 提供的工具（用于契约测试/启动自检）。"""
    async def _h(session):
        resp = await session.list_tools()
        return [
            {"name": t.name, "description": getattr(t, "description", "") or "",
             "inputSchema": getattr(t, "inputSchema", None)}
            for t in resp.tools
        ]
    return await _with_session(_h)


async def get_weather_async(location: str) -> dict[str, Any]:
    """调用 MCP get_weather，返回解析后的 dict（ok 或受控错误信封）。"""
    async def _h(session):
        result = await session.call_tool("get_weather", arguments={"location": location})
        text = ""
        for c in getattr(result, "content", []) or []:
            text += getattr(c, "text", "") or ""
        text = text.strip()
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"status": "error",
                    "error": {"code": "CLIENT_PARSE_ERROR",
                              "message": f"无法解析 MCP 返回：{text[:200]}"}}

    return await _with_session(_h)


# ---- 同步包装（供 LangChain 工具在同步上下文调用） ----
def discover_tools() -> list[dict[str, Any]]:
    return asyncio.run(discover_tools_async())


def get_weather(location: str) -> dict[str, Any]:
    """同步包装：经 MCP stdio 查询天气，返回 dict。"""
    return asyncio.run(get_weather_async(location))
