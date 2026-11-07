"""最终回答净化（纯函数，无外部依赖，便于单测）。

职责：把模型流式产出的“最终回答”中的思考/工具噪声剥掉，只向用户呈现结论。

需要处理的噪声来源：
- 部分推理模型（如 qwen3 思考模式）会把 <think>...</think> 思考段直接拼进正文；
- 模型偶发把工具调用的 JSON / 函数名残留在文本里；
- 系统提示词要求的“思考过程”若泄漏到最终答案中，需剔除。
"""
from __future__ import annotations

import json
import re

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
# 以 “思考：/Thought:/计划：” 开头的整行（模型把 ReAct 思考写进了最终答案）
_LEADING_THOUGHT_LINE_RE = re.compile(
    r"^\s*(?:思考|分析|思路|计划|Thought|Action Observation|观察)\s*[:：].*$",
    re.IGNORECASE,
)
# 残留的工具调用 JSON 块：{..."tool_calls"...} 或 {"name":...,"arguments":...}
_TOOL_CALL_JSON_RE = re.compile(
    r"\{\s*\"(?:tool_calls|name|arguments|function)\"[^}]*\}",
    re.DOTALL,
)


def sanitize_final_answer(text: str | None) -> str:
    """净化模型最终回答，返回只含结论的干净文本。"""
    if not text:
        return ""

    out = text

    # 1) 去掉 <think>...</think> 整段
    out = _THINK_RE.sub("", out)

    # 2) 去掉残留的工具调用 JSON 片段
    out = _TOOL_CALL_JSON_RE.sub("", out)

    # 3) 逐行剔除明显的“思考过程”行（仅当整行是思考行时）
    kept = []
    for line in out.splitlines():
        if _LEADING_THOUGHT_LINE_RE.match(line):
            continue
        kept.append(line)
    out = "\n".join(kept)

    # 4) 收敛多余空行
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def looks_like_tool_call_json(text: str) -> bool:
    """判断一段文本是否更像模型误吐的工具调用 JSON（而非正常回答）。"""
    if not text:
        return False
    s = text.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return False
    try:
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return False
    return isinstance(obj, dict) and ("tool_calls" in obj or "arguments" in obj or "function" in obj)
