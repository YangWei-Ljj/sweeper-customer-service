"""工具治理中间件（第二轮·执行治理）。

核心逻辑抽成纯函数 run_governed(tool_call, context, executor)，便于单测；
@wrap_tool_call 的 governance 仅做 LangChain 请求 -> 纯函数的薄适配。

在 LangGraph 真正执行工具前后包一层：
1. 调用前用注册表做 schema 校验 + 权限/审批裁决；
2. 未注册 / 入参非法 -> 返回拒绝观察（deny），不执行；
3. risk 工具未获批准 -> 返回"需人工确认"观察，记 approved=declined，不执行；
4. 放行则计时执行，按 max_retries 重试；仍失败则降级兜底（不把异常抛给模型）；
5. 每一步写 agent_steps 轨迹（脱敏入参、耗时、重试/降级标记、token 估算）。

设计约束：
- 任何治理/轨迹异常都不能搞崩主对话（吞掉并打日志）；
- 状态机由 ReactAgent 驱动，本模块只读当前状态用于打标，不强行转移。
"""
from __future__ import annotations

import time
from typing import Any, Callable

from langchain.agents.middleware import wrap_tool_call
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage

from agent.registry import Outcome, estimate_tokens, mask_args
from agent.tool_registry import get_registry
from agent import trace
from utils.logger_handler import logger


def _next_step_no(context: dict) -> int:
    seq = context.get("_step_seq", 0) + 1
    context["_step_seq"] = seq
    return seq


def _current_state(context: dict) -> str:
    sm = context.get("sm")
    return getattr(sm, "state", None).value if sm else "UNKNOWN"


def _deny_message(reason: str) -> str:
    return f"[治理拦截] {reason}。请调整参数或改用其他方式完成该任务。"


def run_governed(
    tool_call: dict[str, Any],
    context: dict[str, Any],
    executor: Callable[[], ToolMessage],
) -> ToolMessage:
    """治理核心（纯函数式，不依赖 LangChain 请求对象，便于单测）。

    :param tool_call: {"name":..., "args":..., "id":...}
    :param context: 运行上下文（run_id / sm / approvals / 步序计数器）
    :param executor: 真正执行工具的零参回调（返回 ToolMessage）
    """
    name = tool_call.get("name", "")
    raw_args = tool_call.get("args", {}) or {}
    call_id = tool_call.get("id", "")
    registry = get_registry()
    spec = registry.get(name)

    step_no = _next_step_no(context)
    state = _current_state(context)
    approved_ids = context.get("approvals", set()) or set()

    decision = registry.authorize(name, raw_args, approved_call_ids=approved_ids, call_id=call_id)
    masked = mask_args(raw_args)

    # 拒绝（未注册 / 入参非法）
    if decision.outcome == Outcome.DENY:
        logger.warning(f"[governance] DENY {name}: {decision.reason}")
        trace.record_step(
            run_id=context.get("run_id", ""), step_no=step_no, state=state,
            event="deny", tool_name=name, args_masked=masked,
            result_summary=decision.reason, approved="na",
            tokens_est=estimate_tokens(decision.reason), note="治理拦截",
        )
        return ToolMessage(
            content=_deny_message(decision.reason),
            tool_call_id=call_id, name=name,
        )

    # 高风险未批准
    if decision.outcome == Outcome.NEED_APPROVAL:
        logger.info(f"[governance] NEED_APPROVAL {name}（未确认，不执行）")
        msg = (
            f"[需人工确认] 工具 {name} 属高风险操作，当前未获得人工确认，已跳过执行。"
            "若用户确认要执行，请先在运行上下文中批准该操作，再重试。"
        )
        trace.record_step(
            run_id=context.get("run_id", ""), step_no=step_no, state=state,
            event="approval", tool_name=name, args_masked=masked,
            result_summary=decision.reason, approved="declined",
            tokens_est=estimate_tokens(msg), note="高风险未确认",
        )
        return ToolMessage(content=msg, tool_call_id=call_id, name=name)

    # 放行：计时执行 + 重试
    max_retries = spec.max_retries if spec else 0
    retried = False
    start = time.perf_counter()
    last_err: Exception | None = None
    result: ToolMessage | None = None

    for attempt in range(max_retries + 1):
        try:
            result = executor()
            last_err = None
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning(f"[governance] 工具 {name} 第{attempt + 1}次失败：{e}")
            if attempt < max_retries:
                retried = True
                time.sleep(0.2)

    duration_ms = int((time.perf_counter() - start) * 1000)

    if result is None:
        err_text = str(last_err)[:200] if last_err else "unknown"
        content = f"[工具暂不可用] {name} 执行失败（已重试 {max_retries} 次）：{err_text}。请基于已有信息回答或提示用户稍后再试。"
        logger.error(f"[governance] 工具 {name} 降级：{err_text}")
        trace.record_step(
            run_id=context.get("run_id", ""), step_no=step_no, state=state,
            event="degrade", tool_name=name, args_masked=masked,
            result_summary=content, duration_ms=duration_ms, retried=retried,
            degraded=True,
            approved="approved" if spec and spec.permission.value == "risk" else "na",
            tokens_est=estimate_tokens(content), note="重试耗尽降级",
        )
        return ToolMessage(content=content, tool_call_id=call_id, name=name)

    content = getattr(result, "content", "") or ""
    trace.record_step(
        run_id=context.get("run_id", ""), step_no=step_no, state=state,
        event="tool_result", tool_name=name, args_masked=masked,
        result_summary=str(content), duration_ms=duration_ms, retried=retried,
        degraded=False,
        approved="approved" if (spec and spec.permission.value == "risk") else "na",
        tokens_est=estimate_tokens(str(content)),
        note="重试命中" if retried else None,
    )
    return result


@wrap_tool_call
def governance(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage],
) -> ToolMessage:
    """LangChain wrap_tool_call 适配：把请求对象解包成纯函数入参。"""
    return run_governed(
        tool_call=request.tool_call or {},
        context=request.runtime.context if request.runtime else {},
        executor=lambda: handler(request),
    )
