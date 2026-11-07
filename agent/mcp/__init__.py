"""MCP 适配层。

工具来源抽象：
- ToolProvider：统一接口（list_tools / call）；
- LocalToolProvider：包装本地函数，默认使用；
- McpStdioProvider：基于官方 mcp SDK 的 stdio client，可直接调用，
  服务器路径由 WEATHER_MCP_SERVER 指定。

边界：server 未配置或调用失败时返回受控错误，不伪造 MCP 返回。
"""
from agent.mcp.base import ToolInfo, ToolProvider
from agent.mcp.local_provider import LocalToolProvider

__all__ = ["ToolInfo", "ToolProvider", "LocalToolProvider"]
