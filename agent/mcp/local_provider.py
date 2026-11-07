"""本地工具 provider：把现有 Python 函数包成统一 ToolProvider 接口。

本阶段所有工具都来自这里；未来天气等可改为 McpStdioProvider 提供，
上层治理/Agent 不改。
"""
from __future__ import annotations

from typing import Any

from agent.mcp.base import ToolInfo, ToolProvider
from agent.registry import ToolRegistry


class LocalToolProvider(ToolProvider):
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def list_tools(self) -> list[ToolInfo]:
        return [
            ToolInfo(name=s.name, description=s.description)
            for s in self._registry.specs()
        ]

    def call(self, name: str, args: dict[str, Any]) -> str:
        spec = self._registry.get(name)
        if spec is None:
            raise KeyError(f"本地未注册工具：{name}")
        result = spec.func(**(args or {}))
        return str(result)
