"""月报生成服务：调用外部记录工具 + 报告提示词 + 大模型，结果持久化。"""
from __future__ import annotations

from agent.tools.agent_tools import fetch_external_data
from model.factory import get_chat_model
from store import save_report
from utils.prompt_loader import load_report_prompts


def generate_report(user_id: str, month: str) -> str | None:
    record = fetch_external_data.invoke({"user_id": user_id, "month": month})
    if not record:
        return None
    prompt = load_report_prompts()
    message = f"{prompt}\n\n请根据以下使用记录生成报告：\n{record}"
    response = get_chat_model().invoke(message)
    content = response.content
    save_report(user_id, month, content)
    return content
