"""工具来源抽象基类。

让"本地硬编码函数"与"MCP 远程工具"对上层（治理层/Agent）呈现同一接口，
从而天气等外部工具未来可从 Local 切到 MCP 而不改动调用方。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolInfo:
    name: str
    description: str = ""
    # MCP 工具的 JSON Schema（本地工具为 None，由注册表 pydantic 模型描述）
    json_schema: dict[str, Any] | None = field(default=None)


class ToolProvider(ABC):
    """统一工具来源接口。"""

    @abstractmethod
    def list_tools(self) -> list[ToolInfo]:
        """列出该来源可用工具。"""

    @abstractmethod
    def call(self, name: str, args: dict[str, Any]) -> str:
        """调用工具并返回字符串结果。"""

    def is_connected(self) -> bool:
        """是否已连接（MCP 远程来源用；本地来源恒 True）。"""
        return True
