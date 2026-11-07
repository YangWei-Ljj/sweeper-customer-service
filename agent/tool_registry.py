"""默认工具注册表装配：把 7 个读工具 + 3 个模拟风险工具注册进统一 ToolRegistry。

与 LangChain @tool 的关系：
- @tool 对象负责让模型可调用（function-calling schema）；
- 这里负责治理元数据（权限/审批/超时/重试/pydantic 入参模型）；
- 二者通过工具名对齐。
"""
from __future__ import annotations

from agent.registry import (
    FetchExternalArgs,
    NoArgs,
    OrderConsumablesArgs,
    Permission,
    RagQuery,
    ResetDeviceArgs,
    ToolRegistry,
    ToolSpec,
    WeatherCity,
    WorkOrderArgs,
)
from agent.tools.agent_tools import (
    fetch_external_data,
    fill_context_for_report,
    get_current_month,
    get_user_id,
    get_user_location,
    rag_summarize,
)
from agent.tools.mcp_weather import get_weather
from agent.tools.risk_tools import (
    create_work_order,
    order_consumables,
    reset_device,
)


def _raw(tool_obj):
    """取 @tool 装饰对象背后的原始 Python 函数。"""
    return getattr(tool_obj, "func", tool_obj)


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    specs = [
        ToolSpec(
            name="rag_summarize", func=_raw(rag_summarize),
            args_model=RagQuery, permission=Permission.READ,
            description="检索知识库并总结", timeout_s=15.0, max_retries=0,
        ),
        ToolSpec(
            name="get_weather", func=_raw(get_weather),
            args_model=WeatherCity, permission=Permission.READ,
            description="获取城市实时天气（经 MCP stdio 天气服务，可重试 1 次）",
            timeout_s=15.0, max_retries=1,
        ),
        ToolSpec(
            name="get_user_location", func=_raw(get_user_location),
            args_model=NoArgs, permission=Permission.READ,
            description="获取用户所在城市",
        ),
        ToolSpec(
            name="get_user_id", func=_raw(get_user_id),
            args_model=NoArgs, permission=Permission.READ,
            description="获取用户ID",
        ),
        ToolSpec(
            name="get_current_month", func=_raw(get_current_month),
            args_model=NoArgs, permission=Permission.READ,
            description="获取当前月份 YYYY-MM",
        ),
        ToolSpec(
            name="fetch_external_data", func=_raw(fetch_external_data),
            args_model=FetchExternalArgs, permission=Permission.READ,
            description="读取用户某月使用记录（本地 CSV）",
            timeout_s=5.0, max_retries=0,
        ),
        ToolSpec(
            name="fill_context_for_report", func=_raw(fill_context_for_report),
            args_model=NoArgs, permission=Permission.READ,
            description="触发报告提示词动态切换",
        ),
        # ---- 高风险（需人工确认，dry-run） ----
        ToolSpec(
            name="create_work_order", func=_raw(create_work_order),
            args_model=WorkOrderArgs, permission=Permission.RISK,
            require_approval=True, description="创建报修工单（高风险，需人工确认）",
            timeout_s=5.0, max_retries=0,
        ),
        ToolSpec(
            name="reset_device", func=_raw(reset_device),
            args_model=ResetDeviceArgs, permission=Permission.RISK,
            require_approval=True, description="重置设备（高风险，需人工确认）",
            timeout_s=5.0, max_retries=0,
        ),
        ToolSpec(
            name="order_consumables", func=_raw(order_consumables),
            args_model=OrderConsumablesArgs, permission=Permission.RISK,
            require_approval=True, description="下单耗材（高风险，需人工确认）",
            timeout_s=5.0, max_retries=0,
        ),
    ]
    for s in specs:
        reg.register(s)
    return reg


# 进程内单例（懒加载，避免导入期重依赖）
_default_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = build_default_registry()
    return _default_registry
