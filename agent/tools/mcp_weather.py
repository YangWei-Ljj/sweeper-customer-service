"""经 MCP 的天气工具（替换原 wttr.in HTTP 直连）。

- 通过 agent.mcp.client 以 stdio 拉起 weather-mcp-server 子进程；
- 错误码映射为对用户友好的文案（不把堆栈/技术错误抛给用户）；
- 返回字符串供模型使用；原始 dict 也可被治理层/轨迹消费。
"""
from __future__ import annotations

from langchain_core.tools import tool

from agent.mcp import client as mcp_client
from utils.logger_handler import logger

# 受控错误码 -> 对用户友好的中文文案
_ERROR_TEXT = {
    "CITY_NOT_ALLOWED": "暂不支持该城市的天气查询，目前仅支持部分主要城市。",
    "MISSING_TOKEN": "天气服务暂未配置访问凭据，暂时无法获取实时天气。",
    "UPSTREAM_TIMEOUT": "天气上游接口超时，请稍后再试。",
    "UPSTREAM_ERROR": "天气服务暂时不可用，请稍后再试。",
    "UPSTREAM_PARSE_ERROR": "天气返回数据异常，暂时无法解析。",
    "CLIENT_PARSE_ERROR": "天气服务返回格式异常。",
}


def render_weather(result: dict) -> str:
    """把 MCP 返回 dict 渲染成给模型/用户的字符串。"""
    if result.get("status") == "ok":
        d = result.get("data", {})
        return (
            f"城市{d.get('location','')}当前天气：{d.get('text','')}，"
            f"气温{d.get('temp_c','')}℃（{d.get('low','')} ~ {d.get('high','')}），"
            f"来源={d.get('source','')}"
        )
    err = result.get("error", {})
    code = err.get("code", "UNKNOWN")
    logger.warning(f"[mcp_weather] 受控错误 {code}: {err.get('message')}")
    return _ERROR_TEXT.get(code, f"暂时无法获取天气（{code}），请稍后再试。")


@tool(description="获取指定城市的实时天气（经 MCP 天气服务），以消息字符串形式返回")
def get_weather(location: str) -> str:
    try:
        result = mcp_client.get_weather(location)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[mcp_weather] MCP 调用失败：{e}")
        return "暂时无法连接天气服务（MCP），请稍后再试。"
    return render_weather(result)
