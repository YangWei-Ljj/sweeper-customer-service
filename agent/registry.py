"""工具注册表与治理裁决（第二轮·执行治理核心）。

每个工具在注册表中**显式声明**：
- name / description / 实际可调用函数；
- args_model：pydantic 入参模型（调用前做 JSON Schema 校验）；
- permission：read / write / risk；
- require_approval：risk 工具默认 True，需人工确认才执行；
- timeout_s / max_retries：资源上限与重试策略。

authorize() 在工具真正执行前裁决：
- 未注册 -> DENY
- 入参不合法 -> DENY（附校验错误）
- risk 且运行上下文未批准 -> NEED_APPROVAL
- 否则 -> ALLOW（返回校验后的规范化参数）

本模块不碰模型/网络；纯治理逻辑，便于单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError


class Permission(str, Enum):
    READ = "read"       # 只读（RAG/天气/上下文/CSV）
    WRITE = "write"     # 本地写（本阶段无普通写工具，预留）
    RISK = "risk"       # 有副作用/需人工确认（删除/重置/下单/派单）


# ---------- 入参 pydantic 模型 ----------
class NoArgs(BaseModel):
    """无入参工具的占位模型。"""


class RagQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)


class WeatherCity(BaseModel):
    location: str = Field(..., min_length=1, max_length=50)


class FetchExternalArgs(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=32)
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$")


class WorkOrderArgs(BaseModel):
    issue: str = Field(..., min_length=1, max_length=500)
    contact: str = Field("", max_length=64)


class ResetDeviceArgs(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)


class OrderConsumablesArgs(BaseModel):
    item: str = Field(..., min_length=1, max_length=128)
    qty: int = Field(1, ge=1, le=100)


# ---------- 裁决结果 ----------
class Outcome(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    NEED_APPROVAL = "need_approval"


@dataclass
class Authorization:
    outcome: Outcome
    normalized: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


# ---------- 工具声明 ----------
@dataclass
class ToolSpec:
    name: str
    func: Callable[..., Any]
    args_model: type[BaseModel]
    permission: Permission
    description: str
    require_approval: bool = False
    timeout_s: float = 15.0
    max_retries: int = 0


class ToolRegistry:
    """进程内工具注册表（白名单）。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [self._tools[n] for n in self.names()]

    def authorize(
        self,
        name: str,
        raw_args: dict[str, Any] | None,
        approved_call_ids: set[str] | None = None,
        call_id: str = "",
    ) -> Authorization:
        """调用前裁决。

        :param name: 工具名
        :param raw_args: 模型产出的原始参数
        :param approved_call_ids: 运行上下文里已被人工批准的 tool_call_id 集合
        :param call_id: 本次 tool_call 的 id（用于审批匹配）
        """
        spec = self.get(name)
        if spec is None:
            return Authorization(Outcome.DENY, reason=f"工具 {name} 未在白名单注册")

        raw = raw_args or {}
        try:
            normalized = spec.args_model(**raw).model_dump()
        except ValidationError as e:
            first = e.errors()[0]
            loc = ".".join(str(x) for x in first.get("loc", []))
            return Authorization(
                Outcome.DENY,
                reason=f"工具 {name} 入参校验失败 [{loc}]: {first.get('msg')}",
            )

        approved_call_ids = approved_call_ids or set()
        if spec.permission == Permission.RISK and spec.require_approval:
            if call_id not in approved_call_ids:
                return Authorization(
                    Outcome.NEED_APPROVAL,
                    normalized=normalized,
                    reason=f"工具 {name} 为高风险操作，需人工确认后执行",
                )

        return Authorization(Outcome.ALLOW, normalized=normalized)


# ---------- 脱敏工具（供轨迹使用，集中在此避免散落） ----------
_SENSITIVE_KEYS = {"user_id", "contact", "phone", "device_id"}


def mask_args(args: dict[str, Any]) -> dict[str, Any]:
    """对入参做脱敏：敏感字段打码，其余原样返回。"""
    if not isinstance(args, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in args.items():
        if k in _SENSITIVE_KEYS and isinstance(v, str) and len(v) > 2:
            out[k] = v[:1] + "***" + v[-1:]
        elif k in ("city", "location") and isinstance(v, str) and v:
            out[k] = v[0] + "*" * (max(0, len(v) - 1))
        else:
            out[k] = v
    return out


def estimate_tokens(text: str | None) -> int:
    """粗估 token 数（中文约 1.5 字/token，英文约 4 字符/token），仅用于可观测，非精确计费。"""
    if not text:
        return 0
    return max(1, len(text) // 2)
