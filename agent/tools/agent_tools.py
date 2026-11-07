"""智能体工具集（改造版）。

修复点：
- get_current_month：写死 2025 -> 改为真实当前月份；
- get_weather：假文案 -> 改为 wttr.in 免费接口（失败时明确提示）；
- get_user_id / get_user_location：random -> 改为从请求上下文读取（可由界面设置）；
- fetch_external_data：split(",") -> 改为 csv 模块解析；
- 所有重资源（RAG、外部数据）延迟初始化，导入期不再创建模型/向量库。
"""
from __future__ import annotations

import contextvars
import csv
import os
from datetime import datetime

from langchain_core.tools import tool

from utils.config_handler import agent_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path

# 请求级上下文：由 ReactAgent 在每次请求时注入（用户ID、城市）
CURRENT_USER_ID: contextvars.ContextVar[str] = contextvars.ContextVar("current_user_id", default="1001")
CURRENT_LOCATION: contextvars.ContextVar[str] = contextvars.ContextVar("current_location", default="杭州")

_external_data: dict[str, dict[str, dict]] = {}


def _rag_service():
    """延迟加载 RAG 服务，避免导入期初始化模型。"""
    from rag.rag_service import RagSummarizeService

    return RagSummarizeService()


@tool(description="从向量存储中检索扫地机器人的知识库参考资料，并给出总结")
def rag_summarize(query: str) -> str:
    return _rag_service().rag_summarize(query)


# 天气工具已迁移至 agent/tools/mcp_weather.py（经 MCP stdio 调用 weather-mcp-server），
# 不再使用 wttr.in 直连 HTTP。


@tool(description="获取用户所在城市的名称，以纯字符串形式返回")
def get_user_location() -> str:
    return CURRENT_LOCATION.get()


@tool(description="获取用户的ID，以纯字符串形式返回")
def get_user_id() -> str:
    return CURRENT_USER_ID.get()


@tool(description="获取当前月份（格式 YYYY-MM），以纯字符串形式返回")
def get_current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _load_external_data() -> None:
    """用 csv 模块解析外部记录（字段含竖线/转义，不能用 split(',')）。"""
    if _external_data:
        return
    path = get_abs_path(agent_conf["external_data_path"])
    if not os.path.exists(path):
        raise FileNotFoundError(f"外部数据文件{path}不存在")
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 6:
                continue
            user_id, feature, efficiency, consumables, comparison, month = (c.strip() for c in row[:6])
            _external_data.setdefault(user_id, {})[month] = {
                "特征": feature,
                "效率": efficiency,
                "耗材": consumables,
                "对比": comparison,
            }


@tool(description="从外部系统中获取指定用户在指定月份的使用记录，以纯字符串形式返回，如果未检索到返回空字符串")
def fetch_external_data(user_id: str, month: str) -> str:
    _load_external_data()
    record = _external_data.get(user_id, {}).get(month)
    if not record:
        logger.warning(f"[fetch_external_data]未检索到用户{user_id}在{month}的记录")
        return ""
    lines = [f"用户{user_id}在{month}的使用记录："]
    for k, v in record.items():
        lines.append(f"{k}：{v}")
    return "\n".join(lines)


@tool(description="无入参，调用后触发报告生成场景的提示词动态切换（由中间件识别）")
def fill_context_for_report() -> str:
    return "fill_context_for_report已调用"


def list_available_user_months() -> dict[str, list[str]]:
    """供界面/报告使用：返回 {user_id: [月份...]}。"""
    _load_external_data()
    return {uid: sorted(months.keys()) for uid, months in _external_data.items()}
