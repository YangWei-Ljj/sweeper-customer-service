import json
from typing import Callable
from utils.prompt_loader import load_system_prompts, load_report_prompts
from langchain.agents import AgentState
from langchain.agents.middleware import wrap_tool_call, before_model, dynamic_prompt, ModelRequest
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from utils.logger_handler import logger

# 同一 (工具名, 参数) 被累计调用达到该次数即判定为循环，强制停止工具调用
MAX_IDENTICAL_TOOL_CALLS = 3


def loop_decision(ctx: dict, name: str, args: dict) -> tuple[bool, int]:
    """纯函数：记录一次 (工具名, 参数) 调用并判定是否应停止。

    :return: (是否应停止, 当前累计重复次数)
    """
    history = ctx.setdefault("_tool_call_history", [])
    key = json.dumps({"name": name, "args": args or {}}, sort_keys=True, ensure_ascii=False)
    history.append(key)
    repeat = history.count(key)
    return repeat >= MAX_IDENTICAL_TOOL_CALLS, repeat


@wrap_tool_call
def monitor_tool(
        # 请求的数据封装
        request: ToolCallRequest,
        # 执行的函数本身
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:             # 工具执行的监控
    logger.info(f"[tool monitor]执行工具：{request.tool_call['name']}")
    logger.info(f"[tool monitor]传入参数：{request.tool_call['args']}")

    try:
        result = handler(request)
        logger.info(f"[tool monitor]工具{request.tool_call['name']}调用成功")

        if request.tool_call['name'] == "fill_context_for_report":
            request.runtime.context["report"] = True

        return result
    except Exception as e:
        logger.error(f"工具{request.tool_call['name']}调用失败，原因：{str(e)}")
        raise e


@wrap_tool_call
def loop_guard(
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """循环保护：统计同一 (工具名+参数) 在本次任务中的累计调用次数。

    达到上限时不再真正执行工具，而是回传一条“强制停止”观察消息，
    提示模型基于已有信息直接回答——防止模型陷入重复调用同一工具的死循环。
    这是应用层软保护；图级 recursion_limit 作为最后硬兜底。
    """
    ctx = request.runtime.context
    should_stop, repeat = loop_decision(ctx, request.tool_call["name"], request.tool_call.get("args", {}))

    if should_stop:
        logger.warning(
            f"[loop_guard]检测到循环：工具{request.tool_call['name']}相同参数已累计调用{repeat}次，强制停止"
        )
        return ToolMessage(
            content=(
                f"[循环保护] 工具 {request.tool_call['name']} 以相同参数已被连续调用 {repeat} 次，"
                f"系统判定为重复调用并已停止工具执行。请不要再调用任何工具，直接基于已有信息向用户给出最终回答。"
            ),
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
        )

    return handler(request)


@before_model
def log_before_model(
        state: AgentState,          # 整个Agent智能体中的状态记录
        runtime: Runtime,           # 记录了整个执行过程中的上下文信息
):         # 在模型执行前输出日志
    logger.info(f"[log_before_model]即将调用模型，带有{len(state['messages'])}条消息。")

    logger.debug(f"[log_before_model]{type(state['messages'][-1]).__name__} | {state['messages'][-1].content.strip()}")

    return None


@dynamic_prompt                 # 每一次在生成提示词之前，调用此函数
def report_prompt_switch(request: ModelRequest):     # 动态切换提示词
    is_report = request.runtime.context.get("report", False)
    if is_report:               # 是报告生成场景，返回报告生成提示词内容
        return load_report_prompts()

    return load_system_prompts()
